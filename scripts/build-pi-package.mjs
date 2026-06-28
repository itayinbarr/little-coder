#!/usr/bin/env node
/**
 * Build a pi package from the little-coder source tree.
 * This creates a package that can be published as `little-coder-pi` (or similar)
 * and installed via `npm install little-coder-pi` to get the extensions/skills.
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

// Extensions to include in the pi package (subset of all little-coder extensions)
// These are the ones most useful for vanilla pi users
const PI_PACKAGE_EXTENSIONS = [
	"_shared",
	"extra-tools",
	"output-parser",
	"permission-gate",
	"prompt-history",
	"quality-monitor",
	"read-guard",
	"read-guard-edit",
	"skill-inject",
	"thinking-budget",
	"write-guard",
	"checkpoint",
	"evidence",
	"evidence-compact",
	"knowledge-inject",
	"tool-gating",
	"browser",
	"browser-extract-retention",
	"shell-session",
	"subagent",
	"plan-mode",
	"finalize-warn",
];

// Extensions to register as pi extensions (excludes _shared which is a utility module)
const PI_PACKAGE_PI_EXTENSIONS = PI_PACKAGE_EXTENSIONS.filter(
	(e) => e !== "_shared",
);

// Skills to include (copied for extensions to load internally)
// These are NOT standalone pi skills - they're loaded by their extensions
// tools/*    -> skill-inject extension (type: tool-guidance)
// knowledge/* -> knowledge-inject extension (type: domain-knowledge)
// protocols/* -> protocols extension (type: workflow)
const PI_PACKAGE_SKILL_DIRS = ["tools", "knowledge", "protocols"];

const outDir = join(root, "dist", "pi-package");
const extSrcDir = join(root, ".pi", "extensions");
const skillsSrcDir = join(root, "skills");

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

// Clean and create output directory
rmSync(outDir, { recursive: true, force: true });
mkdirSync(outDir, { recursive: true });
mkdirSync(join(outDir, "extensions"), { recursive: true });
mkdirSync(join(outDir, "skills"), { recursive: true });

// Copy extensions
for (const ext of PI_PACKAGE_EXTENSIONS) {
	const src = join(extSrcDir, ext);
	const dest = join(outDir, "extensions", ext);
	if (!existsSync(src)) {
		console.warn(`Warning: Extension not found: ${ext}`);
		continue;
	}
	cpSync(src, dest, { recursive: true });
	console.log(`Copied extension: ${ext}`);
	// Prune test files after copy
	pruneTests(dest);
}

// Copy skills
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

// Create package.json for the pi package
const piPackageJson = {
	name: "little-coder-pi",
	version,
	description:
		"Pi package providing little-coder extensions and skills for vanilla pi",
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
		"@earendil-works/pi-ai": "*",
		"@earendil-works/pi-coding-agent": "*",
		"@earendil-works/pi-tui": "*",
	},
	pi: {
		extensions: PI_PACKAGE_PI_EXTENSIONS.map((e) => `./extensions/${e}`),
		skills: [],
	},
	devDependencies: {
		"@earendil-works/pi-ai": "^0.80.0",
		"@earendil-works/pi-coding-agent": "^0.80.0",
		"@earendil-works/pi-tui": "^0.80.0",
	},
};

writeFileSync(
	join(outDir, "package.json"),
	JSON.stringify(piPackageJson, null, 2) + "\n",
);

// Create UPSTREAM.json with provenance
writeFileSync(
	join(outDir, "UPSTREAM.json"),
	JSON.stringify(
		{
			source: pkg.repository.url,
			version,
			builtAt: new Date().toISOString(),
			included: {
				extensions: PI_PACKAGE_EXTENSIONS,
				skills: PI_PACKAGE_SKILL_DIRS,
			},
		},
		null,
		2,
	) + "\n",
);

// Create README.md
const readme = `# little-coder-pi

Pi package providing [little-coder](https://github.com/itayinbarr/little-coder) extensions and skills for vanilla pi.

## Install

\`\`\`bash
npm install little-coder-pi
\`\`\`

This will auto-load all included extensions and skills via pi's package system.

## What's Included

### Extensions (${PI_PACKAGE_EXTENSIONS.length})
${PI_PACKAGE_EXTENSIONS.map((e) => `- ${e}`).join("\n")}

### Skills (${PI_PACKAGE_SKILL_DIRS.length})
${PI_PACKAGE_SKILL_DIRS.map((s) => `- ${s}`).join("\n")}

## Upstream

Built from little-coder v${version}. See [UPSTREAM.json](./UPSTREAM.json) for details.

## License

Apache-2.0 — see little-coder [LICENSE](https://github.com/itayinbarr/little-coder/blob/main/LICENSE).
`;

writeFileSync(join(outDir, "README.md"), readme);

console.log(`\nPi package built at: ${outDir}`);
console.log(`Run 'npm publish' from that directory to publish.`);
