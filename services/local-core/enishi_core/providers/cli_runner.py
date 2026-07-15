"""CLI実行ヘルパー。"""

import asyncio
import subprocess
from pathlib import Path


def run_cli(args: list[str], cwd: Path | None = None, timeout: int = 30) -> tuple[int, str]:
    """シェルを介さず引数配列でCLIを実行する。"""
    try:
        result = subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, OSError):
        return -1, ""
    return result.returncode, result.stdout


async def run_cli_async(
    args: list[str],
    cwd: Path | None = None,
    timeout: int = 600,
    terminate_grace_seconds: float = 3.0,
) -> tuple[int, str]:
    """キャンセル・タイムアウト時に子プロセスをterminate→killで停止する。"""
    process = await asyncio.create_subprocess_exec(
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        stdout, _stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except (TimeoutError, asyncio.CancelledError):
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=terminate_grace_seconds)
            except TimeoutError:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
        raise
    return process.returncode or 0, stdout.decode("utf-8", errors="replace")
