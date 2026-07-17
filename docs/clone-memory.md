# Clones and memory

## Implemented

- A new `CloneAgent` starts in `review_required` and cannot represent the user until activated.
- `ensure_clone` reuses an active clone or pending draft before creating another version.
- Local `MemoryItem` records cover preferences, relationships, communication style, identity, skills, policy, schedule, and environment context.
- Clone rebuilding creates a versioned profile from eligible memories and records confidence and provenance.
- `CloneContextPackage` builds a minimal, task-scoped snapshot for external coding providers.
- Secret memories are excluded from context packages. Peer disclosure policy limits the types and sensitivity that negotiation may use.
- Delegation rules and approval rules are evaluated separately. Destructive or externally visible work cannot silently pass through a clone.
- The desktop UI explains the active clone's memory basis, confidence, delegation boundary, and approval gate without displaying secret content.

## Presentation scenario

The presentation seed creates two users with separate clones and local memories. Their agents compare scheduling preferences without sending raw calendars. A relationship rule on the presenter's node forces the final proposal into human approval. The same seed also registers a restricted local project and completes a harmless mock AI task to show project-scoped delegation.
