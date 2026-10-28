// Focused Adjust Load typecheck plus a full-app no-new-diagnostics guard.
const ts = require('typescript');
const path = require('node:path');
const cp = require('node:child_process');
const dashboard = path.resolve(__dirname, '..');
const root = path.resolve(dashboard, '..');
process.chdir(dashboard);
const git = (...args) => cp.execFileSync('git', args, { cwd: root, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim();
const base = git('merge-base', 'HEAD', process.argv[2] || 'origin/main');
const normalize = p => path.resolve(p).replaceAll('\\', '/').toLowerCase();
const changed = [...new Set([
  ...git('diff', base, '--name-only', '--', 'dashboard/src').split('\n'),
  ...git('ls-files', '--others', '--exclude-standard', 'dashboard/src').split('\n'),
])].filter(p => /\.tsx?$/.test(p));
const previous = new Map();
const added = new Set();
for (const file of changed) {
  try { previous.set(normalize(path.join(root, file)), git('show', `${base}:${file}`)); }
  catch { added.add(normalize(path.join(root, file))); }
}
const configPath = path.join(dashboard, 'tsconfig.app.json');
const config = ts.readConfigFile(configPath, ts.sys.readFile);
if (config.error) throw new Error(ts.flattenDiagnosticMessageText(config.error.messageText, '\n'));
const parsed = ts.parseJsonConfigFileContent(config.config, ts.sys, dashboard);
const focus = [
  'src/components/dispatch/AdjustInventoryModal.tsx', 'src/components/dispatch/TransfersRadarModal.tsx',
  'src/features/dispatch/adjustLoad.ts', 'src/features/dispatch/routeTransfers.ts',
  'src/features/dispatch/useAdjustLoadCommand.ts', 'src/i18n/dispatchAdjustLoad.ts',
  'src/test/dispatch-adjust-load.test.tsx', 'src/test/setup.ts',
  'src/components/dispatch/RouteLoadProductTable.tsx', 'src/components/dispatch/RouteManagementModal.tsx',
  'src/components/dispatch/ShortageModal.tsx', 'src/components/dispatch/ShortageProductPicker.tsx',
  'src/test/dispatch-product-discovery.test.tsx',
].map(file => path.join(dashboard, file));
function diagnostics(baseline, scoped = false) {
  const host = ts.createCompilerHost(parsed.options);
  const read = host.readFile.bind(host), exists = host.fileExists.bind(host);
  if (baseline) {
    host.readFile = file => added.has(normalize(file)) ? undefined : previous.get(normalize(file)) ?? read(file);
    host.fileExists = file => !added.has(normalize(file)) && exists(file);
    host.getSourceFile = (file, language) => {
      const source = host.readFile(file);
      return source === undefined ? undefined : ts.createSourceFile(file, source, language);
    };
  }
  const files = scoped ? focus.concat(parsed.fileNames.filter(file => file.endsWith('.d.ts')))
    : parsed.fileNames.filter(file => !baseline || !added.has(normalize(file)));
  const program = ts.createProgram(files, parsed.options, host);
  return [...parsed.errors, ...ts.getPreEmitDiagnostics(program)].map(diagnostic => ({
    file: diagnostic.file ? path.relative(root, diagnostic.file.fileName).replaceAll('\\', '/') : '<config>',
    code: diagnostic.code, message: ts.flattenDiagnosticMessageText(diagnostic.messageText, '\n'),
  }));
}
const baseline = diagnostics(true), current = diagnostics(false), scoped = diagnostics(false, true);
const key = d => `${d.file}|${d.code}|${d.message}`;
const remaining = new Map();
for (const d of baseline) remaining.set(key(d), (remaining.get(key(d)) || 0) + 1);
const regressions = current.filter(d => {
  const count = remaining.get(key(d)) || 0;
  remaining.set(key(d), count - 1);
  return count === 0;
});
console.log(JSON.stringify({ base, baselineCount: baseline.length, currentCount: current.length,
  newDiagnostics: regressions, scopedDiagnostics: scoped }, null, 2));
process.exitCode = regressions.length || scoped.length ? 1 : 0;
