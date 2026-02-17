# Documentation

Hosted documentation assets for thebrain-mcp. Diagrams and figures are stored here so they can be referenced by raw GitHub URL in TheBrain notes, READMEs, and other documentation.

## Structure

```
docs/
├── README.md          ← this file
└── diagrams/          ← architecture and protocol flow diagrams
```

## Conventions

- **Naming**: Use descriptive, purpose-scoped filenames (e.g., `tollbooth-protocol-flow.svg`, not `diagram1.svg`)
- **Format**: Prefer SVG for diagrams (scalable, versionable, diffable)
- **Fonts**: Use system fonts only — no external font dependencies
- **URL pattern**: Reference via `https://raw.githubusercontent.com/lonniev/thebrain-mcp/main/docs/diagrams/<filename>`

## Adding a New Diagram

1. Create the SVG in `docs/diagrams/`
2. Add an entry to [`docs/diagrams/README.md`](diagrams/README.md)
3. Commit on a feature branch and PR to main
