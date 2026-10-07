/** Check every current source file and reject diagnostics added by this change.
 * Existing main diagnostics are reported, never counted as a passing full tsc.
 * The baseline is an unmodified Git archive/checkout, using the same dependencies.
 */
import fs from "node:fs";
import path from "node:path";
import ts from "typescript";

const root = process.cwd();
const baseline = path.resolve(process.argv[2] ?? "");
if (!process.argv[2] || !fs.existsSync(path.join(baseline, "src"))) throw new Error("Provide an unmodified baseline dashboard directory");
const configPath = path.join(root, "tsconfig.app.json");
const config = ts.readConfigFile(configPath, ts.sys.readFile);
if (config.error) throw new Error(ts.flattenDiagnosticMessageText(config.error.messageText, "\n"));
const parsed = ts.parseJsonConfigFileContent(config.config, ts.sys, root);
const sourceRoot = path.join(root, "src") + path.sep;
const normalize = file => path.resolve(file);
const oldPath = file => path.join(baseline, path.relative(root, normalize(file)));
const isSource = file => normalize(file).startsWith(sourceRoot);
function diagnostics(useBaseline) {
  const host = ts.createCompilerHost(parsed.options);
  if (useBaseline) {
    const read = host.readFile;
    const exists = host.fileExists;
    host.readFile = file => isSource(file) ? ts.sys.readFile(oldPath(file)) : read(file);
    host.fileExists = file => isSource(file) ? ts.sys.fileExists(oldPath(file)) : exists(file);
  }
  const files = useBaseline ? parsed.fileNames.filter(file => fs.existsSync(oldPath(file))) : parsed.fileNames;
  const program = ts.createProgram(files, parsed.options, host);
  return ts.getPreEmitDiagnostics(program).filter(d => d.category === ts.DiagnosticCategory.Error).map(d => ({
    file: d.file ? path.relative(root, d.file.fileName).replaceAll("\\", "/") : "config",
    code: d.code, message: ts.flattenDiagnosticMessageText(d.messageText, " "),
  }));
}
const before = diagnostics(true);
const current = diagnostics(false);
const counts = new Map();
for (const error of before) { const key = JSON.stringify(error); counts.set(key, (counts.get(key) ?? 0) + 1); }
const introduced = current.filter(error => {
  const key = JSON.stringify(error); const left = counts.get(key) ?? 0;
  if (left === 0) return true;
  counts.set(key, left - 1); return false;
});
console.log(JSON.stringify({ baseline_errors: before.length, current_errors: current.length, introduced }, null, 2));
process.exitCode = introduced.length > 0 ? 1 : 0;
