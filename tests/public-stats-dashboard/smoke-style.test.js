import { describe, expect, it } from "vitest";
import { readFileSync, existsSync } from "node:fs";
import { join } from "node:path";

const root = process.cwd();

describe("public stats dashboard static deployable and style", () => {
  it("ships as static assets with index document and no bundler", () => {
    const index = readFileSync(join(root, "src", "index.html"), "utf8");
    expect(index).toContain("<script type=\"module\" src=\"./app.js\"></script>");
    expect(index).toContain("<script src=\"./config.js\"></script>");
    expect(index).toContain("<link rel=\"stylesheet\" href=\"./styles.css\" />");
    expect(index).toContain("./assets/OPUS-logo.png");
    expect(existsSync(join(root, "src", "assets", "OPUS-logo.png"))).toBe(true);
    expect(existsSync(join(root, "src", "config.js"))).toBe(true);
    const packageJson = readFileSync(join(root, "package.json"), "utf8");
    expect(packageJson).not.toMatch(/webpack|vite\s+--host|parcel|react|next/);
  });

  it("uses Opus tokens, gradient, card style, and Roboto stack", () => {
    const css = readFileSync(join(root, "src", "styles.css"), "utf8");
    expect(css).toContain('font-family: "Roboto", Arial, Helvetica, sans-serif;');
    expect(css).toContain("linear-gradient(135deg, #004851 0%, #00968F 58%, #93D500 100%)");
    expect(css).toContain("--opus-orange: #FF8200;");
    expect(css).toContain("box-shadow: 0 8px 24px rgba(19, 30, 41, 0.08);");
    expect(css).toContain("border-radius: 14px;");
  });

  it("keeps accessible contrast for core text tokens", () => {
    expect(contrastRatio("#131E29", "#F4F7F7")).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio("#54565A", "#FFFFFF")).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio("#FFFFFF", "#004851")).toBeGreaterThanOrEqual(3);
  });

  it("documents the demo-only credential constraint", () => {
    const configExample = readFileSync(join(root, "src", "config.example.js"), "utf8");
    const design = readFileSync(join(root, ".kiro", "specs", "public-stats-dashboard", "design.md"), "utf8");
    expect(configExample).toContain("not production-safe");
    expect(design).toContain("Embedding a `Client_Credential` in a publicly hosted static site exposes that credential");
  });
});

function contrastRatio(foreground, background) {
  const l1 = relativeLuminance(foreground);
  const l2 = relativeLuminance(background);
  const lighter = Math.max(l1, l2);
  const darker = Math.min(l1, l2);
  return (lighter + 0.05) / (darker + 0.05);
}

function relativeLuminance(hex) {
  const [r, g, b] = hex
    .replace("#", "")
    .match(/.{2}/g)
    .map((value) => parseInt(value, 16) / 255)
    .map((channel) => (channel <= 0.03928 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
