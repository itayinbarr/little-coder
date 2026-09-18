import { describe, it, expect, afterAll } from "vitest";
import { execSync } from "node:child_process";
import { readFileSync, existsSync, rmSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

// Smoke test for the pi package build.
//
// Runs the build, then verifies the produced package is loadable by checking
// the structural invariants a pi loader would rely on: valid package.json with
// the expected name/version/extension list, every listed extension directory
// present with an index.ts, the _shared utility module present, README
// describes behavioral caveats, and UPSTREAM.json records provenance.

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..");
const outDir = join(root, "dist", "pi-package");

function build() {
	execSync("node scripts/build-pi-package.mjs", {
		cwd: root,
		stdio: "pipe",
	});
}

describe("build-pi-package", () => {
	afterAll(() => {
		rmSync(join(root, "dist"), { recursive: true, force: true });
	});

	it("produces a loadable pi package", () => {
		build();

		const pkgPath = join(outDir, "package.json");
		expect(existsSync(pkgPath), "dist/pi-package/package.json missing").toBe(true);
		const pkg = JSON.parse(readFileSync(pkgPath, "utf8"));

		const rootPkg = JSON.parse(
			readFileSync(join(root, "package.json"), "utf8"),
		);
		expect(pkg.name, "package name").toBe("pi-little-coder");
		expect(pkg.version, "package version matches root").toBe(rootPkg.version);

		expect(Array.isArray(pkg.pi?.extensions), "pi.extensions is an array").toBe(true);
		expect(pkg.pi.extensions.length, "pi.extensions is non-empty").toBeGreaterThan(0);
		for (const entry of pkg.pi.extensions) {
			expect(typeof entry, `pi.extensions entry is a string: ${entry}`).toBe("string");
			expect(
				/^\.\/extensions\/[a-z0-9_-]+$/.test(entry),
				`pi.extensions entry matches "./extensions/<name>": ${entry}`,
			).toBe(true);
		}

		expect(
			pkg.pi.extensions.includes("./extensions/_shared"),
			"_shared must not be registered as a pi extension",
		).toBe(false);

		for (const entry of pkg.pi.extensions) {
			const extName = entry.replace(/^\.\/extensions\//, "");
			const extDir = join(outDir, "extensions", extName);
			expect(existsSync(extDir), `extension dir exists: ${extName}`).toBe(true);
			expect(
				existsSync(join(extDir, "index.ts")),
				`extension has index.ts: ${extName}`,
			).toBe(true);
		}

		expect(
			existsSync(join(outDir, "extensions", "_shared")),
			"_shared utility module is copied",
		).toBe(true);

		const readmePath = join(outDir, "README.md");
		expect(existsSync(readmePath), "README.md exists").toBe(true);
		const readme = readFileSync(readmePath, "utf8");
		expect(readme.includes("pi-little-coder"), "README mentions package name").toBe(true);
		expect(
			readme.includes("Behavioral differences outside the little-coder launcher"),
			"README documents behavioral differences caveat",
		).toBe(true);

		const upstreamPath = join(outDir, "UPSTREAM.json");
		expect(existsSync(upstreamPath), "UPSTREAM.json exists").toBe(true);
		const upstream = JSON.parse(readFileSync(upstreamPath, "utf8"));
		expect(typeof upstream.source === "string" && upstream.source.length > 0, "UPSTREAM has source").toBe(true);
		expect(typeof upstream.version === "string" && upstream.version.length > 0, "UPSTREAM has version").toBe(true);
	});
});
