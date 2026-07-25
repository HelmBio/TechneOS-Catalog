# Structure Viewer

Embedded App for the TechneOS platform — a chemical structure
viewer and 2D editor built on [Ketcher](https://github.com/epam/ketcher).

This is the reference implementation for building an embedded App. The platform
runs the Docker image and mounts the running container at
`/api/v1/apps/runtime/structure-viewer/` through its reverse proxy. See
[the App guide](../../docs/guides/app-guide.md) for the full registration
lifecycle.

## Local dev (no container)

```bash
npm install
APP_BASE_PATH= npm run dev
# → http://localhost:3000
```

When running inside the platform, `APP_BASE_PATH` is set to the platform mount
path so Next.js routes and assets resolve correctly.

## Build, register, deploy

```bash
bin/register.sh apps/structure-viewer
```

Authentication is handled by the script. On first run it prompts for admin email +
password and caches the JWT under `~/.techneos/{env}_token.json`; subsequent runs
reuse the cached token until it expires. To skip the prompt non-interactively, pass
`--email` and `--password`.

Common flags (passed straight through):

```bash
--skip-build      # skip the docker build (image already on the host)
--skip-deploy     # register/update the App row but don't trigger /deploy
--upsert          # DELETE then POST instead of PATCH on an existing row
```

The script reads `app_def.json` for the static App metadata and `package.json`'s
`version` for the docker tag.

## Remove

```bash
./bin/unregister.sh app structure-viewer

# Preview without changes
./bin/unregister.sh app structure-viewer --dry-run
```

Calls `DELETE /api/v1/apps/{id}`. The app-service stops the running container and
drops the DB row. Takes a slug or a UUID.

## Platform integration

- `GET /healthz` — health probe used by the App deployer.
- postMessage bridge in `src/lib/platform-bridge.ts` accepts `load_molecule` /
  `ping` from the parent frame, and emits `ready` / `pong` / `molecule_changed`.
