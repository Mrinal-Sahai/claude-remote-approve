# Publishing to the VS Code Marketplace

A step-by-step for shipping `claude-remote-approve` to the Marketplace. One-time
setup is steps 1–3; every release is steps 4–6.

---

## 1. Create a publisher (one time)

The `publisher` in [`package.json`](package.json) is currently **`MrinalSahai`** —
your Marketplace publisher id must match this exactly (or change the field).

1. Go to <https://marketplace.visualstudio.com/manage>.
2. Sign in with a Microsoft account. This creates an **Azure DevOps** org behind
   the scenes (free).
3. Create a publisher: pick an **ID** (e.g. `MrinalSahai`) and a display name.
   - If you choose a different ID, update `"publisher"` in `package.json`.

## 2. Create a Personal Access Token (one time)

`vsce` authenticates with an Azure DevOps PAT — **not** your GitHub token.

1. Go to <https://dev.azure.com> → your org → **User settings → Personal Access
   Tokens → New Token**.
2. Configure:
   - **Organization:** *All accessible organizations* (important).
   - **Scopes:** *Custom defined* → **Marketplace → Manage**.
   - **Expiration:** up to 1 year.
3. Copy the token (shown once).

## 3. Log in (one time per machine)

```bash
npm install -g @vscode/vsce      # or use npx below
vsce login MrinalSahai           # paste the PAT when prompted
```

---

## 4. Pre-release checklist

```bash
cd vscode-extension
npm ci
npm run lint            # tsc --noEmit, must be clean
npm run test:unit       # 9 passing
npm run test:integration # 2 passing (needs a display / xvfb on CI)
npm run package         # builds the .vsix
```

Then **install the .vsix in real VS Code** and smoke-test the setup flow
(see [TESTING.md](TESTING.md) §1):

```bash
code --install-extension claude-remote-approve-0.1.0.vsix
# quit + reopen VS Code, run "Telegram Approve: Setup"
```

Also confirm:
- [ ] `icon.png` is real branding (the shipped one is a placeholder).
- [ ] `README.md` reads well — it becomes the Marketplace page.
- [ ] `CHANGELOG.md` updated.
- [ ] `repository` URL in `package.json` is correct.
- [ ] version bumped (see step 5).

## 5. Bump the version

`vsce` can bump + tag in one go (uses semver):

```bash
vsce publish patch     # 0.1.0 -> 0.1.1
vsce publish minor     # 0.1.0 -> 0.2.0
vsce publish major     # 0.1.0 -> 1.0.0
```

…or set the `version` in `package.json` by hand and run a bare `vsce publish`.

## 6. Publish

```bash
vsce publish                 # if you already logged in (step 3)
# or, without a global install / login:
npx @vscode/vsce publish -p <YOUR_PAT>
```

The extension is live in ~5 minutes. Verify at
`https://marketplace.visualstudio.com/items?itemName=MrinalSahai.claude-remote-approve`.

---

## Optional: Open VSX (Cursor, VSCodium, Windsurf, …)

Editors that aren't MS-branded VS Code use the **Open VSX** registry.

```bash
npm install -g ovsx
# token from https://open-vsx.org (sign in, create an access token)
ovsx publish claude-remote-approve-0.1.0.vsix -p <OPENVSX_TOKEN>
```

---

## Notes & gotchas

- **PAT scope must be *All accessible organizations*** — the #1 cause of
  `401 Unauthorized` on publish.
- **Publisher id mismatch** between `package.json` and the Marketplace → publish
  is rejected. They must be identical.
- **Icon is required for a good listing** but not for publishing; without one the
  Marketplace shows a default.
- **`engines.vscode`** (`^1.85.0`) is the minimum VS Code version users need.
  Don't raise it past APIs you actually use.
- **The bundled Python hooks ship inside the `.vsix`** (`scripts/`). They are
  copied from `../hooks/tg-approve` at build time by `npm run copy-scripts`, so
  always build from the repo (don't publish a stale standalone copy).
- **CI** (`.github/workflows/ci.yml`) runs all three test suites on every push;
  keep it green before publishing.
