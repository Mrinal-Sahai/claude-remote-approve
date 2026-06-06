// Copies the canonical Python hook scripts from ../hooks/tg-approve into the
// extension's bundled scripts/ dir so they ship inside the .vsix.
// The repo's hooks/tg-approve is the single source of truth.
const fs = require("fs");
const path = require("path");

const src = path.resolve(__dirname, "..", "..", "hooks", "tg-approve");
const dst = path.resolve(__dirname, "..", "scripts");

const FILES = [
  "approve.py",
  "dispatcher.py",
  "watcher.py",
  "post_tool.py",
  "tg_common.py",
  "tg_setup.py",
  "detect_chat_id.py",
];

fs.mkdirSync(dst, { recursive: true });
for (const f of FILES) {
  fs.copyFileSync(path.join(src, f), path.join(dst, f));
}
console.log(`copy-scripts: copied ${FILES.length} hook scripts -> scripts/`);
