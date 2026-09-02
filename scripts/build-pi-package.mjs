#!/usr/bin/env node
/**
 * Build a pi package from the little-coder source tree.
 * Auto-discovers extensions from .pi/extensions/ and ships a curated subset.
 */
import {
	cpSync,
	existsSync,
	mkdirSync,
	readFileSync,
	readdirSync,
	rmSync,
	statSync,
	writeFileSync,
} from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..");
let pkg;
try {
	pkg = JSON.parse(readFileSync(join(root, "package.json"), "utf8"));
} catch (e) {
	console.error("Failed to read package.json:", e);
	process.exit(1);
}
const version = pkg.version;
const repoUrl = pkg.repository?.url ?? pkg.homepage ?? "https://github.com/itayinbarr/little-coder";
// Normalize git+https://host/user/repo(.git) and https://host/user/repo to a browsable URL.
const webRepoUrl = repoUrl
	.replace(/^git\+/, "")
	.replace(/\.git$/, "");

// Extensions to exclude from the shipped package.
// PR-review exclusions (little-coder-runtime-specific / benchmark-specific / test):
//   branding         — little-coder-specific TUI branding, no value for vanilla pi
//   benchmark-profiles — benchmark-specific, no pi value
//   evidence         — GAIA benchmark evidence collection, benchmark-specific
//   evidence-compact — GAIA benchmark evidence collection, benchmark-specific
//   hello            — example/test extension
// Dependency-forced exclusions (depends on a PR-review-excluded extension):
//   browser-extract-retention — imports from excluded evidence; would break at load time
//
// NOTE: `llama-cpp-provider` and `phase-model` are intentionally SHIPPED.
// The reviewer explicitly wants `plan-mode` included (it's genuinely useful to
// vanilla pi users), but `plan-mode` statically imports `enterPhase` from
// `phase-model`, which statically imports `resolveOverridePath` from
// `llama-cpp-provider/config.ts`. Without those two the package would NOT be
// loadable. They are therefore kept and documented as runtime dependencies of
// plan-mode.
const EXCLUDED_EXTENSIONS = new Set([
	"branding",
	"benchmark-profiles",
	"evidence",
	"evidence-compact",
	"hello",
	"browser-extract-retention",
]);

const extSrcDir = join(root, ".pi", "extensions");
const skillsSrcDir = join(root, "skills");
const outDir = join(root, "dist", "pi-package");

const allEntries = readdirSync(extSrcDir);
const discoveredExtensions = allEntries.filter((name) => {
	const path = join(extSrcDir, name, "index.ts");
	return existsSync(path);
});

const shippedExtensions = discoveredExtensions.filter(
	(e) => !EXCLUDED_EXTENSIONS.has(e),
);

function pruneTests(dir) {
	if (!existsSync(dir)) return;
	for (const name of readdirSync(dir)) {
		const full = join(dir, name);
		if (statSync(full).isDirectory()) {
			pruneTests(full);
			continue;
		}
		if (name.endsWith(".test.ts")) rmSync(full, { force: true });
	}
}

rmSync(outDir, { recursive: true, force: true });
mkdirSync(outDir, { recursive: true });
mkdirSync(join(outDir, "extensions"), { recursive: true });
mkdirSync(join(outDir, "skills"), { recursive: true });

// Copy _shared first: it is a utility module (no index.ts) that many shipped
// extensions import from, but must NOT be registered as a pi extension.
const sharedSrc = join(extSrcDir, "_shared");
if (existsSync(sharedSrc)) {
	cpSync(sharedSrc, join(outDir, "extensions", "_shared"), { recursive: true });
	console.log("Copied utility module: _shared (not registered as a pi extension)");
	pruneTests(join(outDir, "extensions", "_shared"));
}

// Copy each shipped extension. Excluded extensions are not copied at all.
for (const ext of shippedExtensions) {
	const src = join(extSrcDir, ext);
	const dest = join(outDir, "extensions", ext);
	cpSync(src, dest, { recursive: true });
	console.log(`Copied extension: ${ext}`);
	pruneTests(dest);
}

// Report excluded extensions (only those that actually exist on disk).
for (const ext of discoveredExtensions) {
	if (EXCLUDED_EXTENSIONS.has(ext)) {
		console.warn(`Excluded extension (not shipped): ${ext}`);
	}
}

const PI_PACKAGE_SKILL_DIRS = ["tools", "knowledge", "protocols"];
for (const skillDir of PI_PACKAGE_SKILL_DIRS) {
	const src = join(skillsSrcDir, skillDir);
	const dest = join(outDir, "skills", skillDir);
	if (!existsSync(src)) {
		console.warn(`Warning: Skills directory not found: ${skillDir}`);
		continue;
	}
	cpSync(src, dest, { recursive: true });
	console.log(`Copied skills: ${skillDir}`);
}

const piPackageJson = {
	name: "pi-little-coder",
	version,
	description:
		"Pi package providing a curated subset of little-coder's extension layer — guard rails, tool policies, UI helpers, and skill-injection tools. Ships as a pi package; does not include the little-coder launcher or launcher-level wiring.",
	type: "module",
	license: "Apache-2.0",
	repository: {
		type: "git",
		url: "git+https://github.com/itayinbarr/little-coder.git",
	},
	keywords: [
		"pi-package",
		"pi",
		"little-coder",
		"extensions",
		"skills",
		"coding-agent",
	],
	files: ["extensions/", "skills/", "UPSTREAM.json", "README.md"],
	peerDependencies: {
		"@earendil-works/pi-ai": "^0.83.0",
		"@earendil-works/pi-coding-agent": "^0.83.0",
		"@earendil-works/pi-tui": "^0.83.0",
	},
	pi: {
		extensions: shippedExtensions.map((e) => `./extensions/${e}`),
		skills: [],
	},
	devDependencies: {
		"@earendil-works/pi-ai": "^0.83.0",
		"@earendil-works/pi-coding-agent": "^0.83.0",
		"@earendil-works/pi-tui": "^0.83.0",
	},
};

writeFileSync(
	join(outDir, "package.json"),
	JSON.stringify(piPackageJson, null, 2) + "\n",
);

writeFileSync(
	join(outDir, "UPSTREAM.json"),
	JSON.stringify(
		{
			source: repoUrl,
			version,
			builtAt: new Date().toISOString(),
			included: {
				extensions: shippedExtensions,
				skills: PI_PACKAGE_SKILL_DIRS,
			},
		},
		null,
		2,
	) + "\n",
);

const extListMd = shippedExtensions.map((e) => `- \`${e}\``).join("\n");
const skillListMd = PI_PACKAGE_SKILL_DIRS.map((s) => `- \`${s}\``).join("\n");

const readme = `# pi-little-coder

**A curated subset of little-coder's extension layer, NOT little-coder-in-a-box.**

This package ships extensions and skill-injection content extracted from
[little-coder](${webRepoUrl}) (v${version}). It is a pi package: install it into your pi
install and pi's launcher will auto-load the shipped extensions.

It does **not** include the little-coder launcher or any of the
launcher-level wiring that makes little-coder behave as it does. Several
behaviours you may be used to come from patching pi itself or from
launcher-level code in \`bin/\`, not from extensions — see **Behavioral
differences outside the little-coder launcher** below.

## Install

\`\`\`bash
npm install pi-little-coder
\`\`\`

pi will auto-discover and load the shipped extensions on next launch.

## What's Included

### Extensions (${shippedExtensions.length})

${extListMd}

### Skill categories (${PI_PACKAGE_SKILL_DIRS.length})

${skillListMd}

These \`skills/\` subdirectories are bundled for use by the
\`skill-inject\` and \`knowledge-inject\` extensions; they are not standalone
pi skills.

## Behavioral differences outside the little-coder launcher

A number of little-coder behaviours are **not** shipped in this package because
they live in launcher-level code, not in extensions:

- **pi source patching** — \`scripts/patch-pi.mjs\` re-applies small source edits
  to the installed \`@earendil-works/pi-coding-agent\` on every launch (e.g. suppressing
  pi's bare "Operation aborted" result marker). This is patching pi itself, not
  extending it. Outside the little-coder launcher those edits are absent, so you
  may see that marker surface in aborted runs.

- **Extension loading order** — little-coder launches pi with \`--no-extensions\` and
  then loads extensions in a specific order via explicit \`--extension\` flags. That
  ordering matters for some extensions. The package ships extensions but does not
  control load order; pi's own discovery order is used.

- **Global settings merge** — the launcher writes \`quietStartup\`, pins
  \`lastChangelogVersion\`, and applies other settings to pi's global config.
  Without that wiring, startup may be chattier.

- **llama.cpp context re-probe** — little-coder probes and reconfigures the
  llama.cpp provider's context window on each launch; that logic lives in \`bin/\`.

- **Update flow** — little-coder's update check and \`/update\` command are wired
  in \`bin/\` and in the \`update-notice\` extension. Without the launcher wiring
  that extension degrades gracefully, but may not function as intended.

You may therefore observe different behaviour than in little-coder — for example,
an aborted-run marker may appear, startup may produce more output, or extensions
that rely on specific load ordering may behave differently. This is expected.

## Upstream

Built from [little-coder](${webRepoUrl}) v${version}.
See [UPSTREAM.json](./UPSTREAM.json) for build provenance, shipped extensions, and
skill categories. This package tracks the main little-coder version; when
little-coder ships a new release, a corresponding package release is cut.

## License

Apache-2.0 — see little-coder
[LICENSE](${webRepoUrl}/blob/main/LICENSE).
`;

writeFileSync(join(outDir, "README.md"), readme);

const shipped = shippedExtensions.length;
const excluded = discoveredExtensions.length - shipped;
console.log(
	`\nPi package built at: ${outDir}`,
);
console.log(
	`Shipped: ${shipped} extensions | Excluded: ${excluded} | Skills: ${PI_PACKAGE_SKILL_DIRS.length}`,
);
console.log("Run 'npm publish' from that directory to publish.");
