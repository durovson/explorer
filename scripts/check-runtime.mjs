import { readdir, readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const projectRoot = path.resolve(fileURLToPath(new URL('..', import.meta.url)));
const runtimeRoot = path.join(projectRoot, 'tgcloud');
const allowedSdkModules = new Set(['sdk', 'sdk/db', 'sdk/api', 'sdk/fetch']);
const excludedDirectories = new Set(['node_modules', '.git', '.tgcloud']);
const forbiddenGlobals = new Set(['process', 'Buffer', 'require', 'setTimeout', 'setInterval', 'setImmediate', 'clearTimeout', 'clearInterval', 'clearImmediate']);
const failures = [];
const warnings = [];

async function filesIn(directory) {
  const results = [];
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    if (entry.isSymbolicLink()) { failures.push(`${path.relative(projectRoot, directory)}: символьные ссылки не поддерживаются.`); continue; }
    if (entry.isDirectory()) {
      if (!excludedDirectories.has(entry.name)) results.push(...await filesIn(path.join(directory, entry.name)));
    } else if (entry.isFile()) results.push(path.join(directory, entry.name));
  }
  return results;
}

// Ignore strings/comments when checking runtime identifiers. The VM parser below
// extracts actual static import specifiers, including multiline imports/re-exports.
function codeTokens(source) {
  const tokens = [];
  const stack = [{ mode: 'code', templateExpression: false, depth: 0 }];
  let index = 0;
  while (index < source.length) {
    const context = stack.at(-1);
    const char = source[index];
    if (context.mode === 'template') {
      if (char === '\\') { index += 2; continue; }
      if (char === '`') { stack.pop(); index += 1; continue; }
      if (char === '$' && source[index + 1] === '{') {
        stack.push({ mode: 'code', templateExpression: true, depth: 0 }); index += 2; continue;
      }
      index += 1; continue;
    }
    if (char === '/' && source[index + 1] === '/') {
      index = source.indexOf('\n', index + 2); if (index < 0) break; continue;
    }
    if (char === '/' && source[index + 1] === '*') {
      const end = source.indexOf('*/', index + 2); index = end < 0 ? source.length : end + 2; continue;
    }
    if (char === '"' || char === "'") {
      const quote = char; index += 1;
      while (index < source.length) {
        if (source[index] === '\\') { index += 2; continue; }
        if (source[index++] === quote) break;
      }
      continue;
    }
    if (char === '`') { stack.push({ mode: 'template' }); index += 1; continue; }
    if (char === '{') context.depth += 1;
    if (char === '}') {
      if (context.templateExpression && context.depth === 0) { stack.pop(); index += 1; continue; }
      context.depth -= 1;
    }
    if (/[A-Za-z_$]/u.test(char)) {
      const start = index++;
      while (index < source.length && /[A-Za-z0-9_$]/u.test(source[index])) index += 1;
      tokens.push(source.slice(start, index)); continue;
    }
    if (!/\s/u.test(char)) tokens.push(char);
    index += 1;
  }
  return tokens;
}

const importInspector = `
import vm from 'node:vm';
let source = '';
for await (const chunk of process.stdin) source += chunk;
try {
  const module = new vm.SourceTextModule(source);
  process.stdout.write(JSON.stringify(module.dependencySpecifiers));
} catch {
  process.exitCode = 1;
}
`;

const allFiles = await filesIn(projectRoot);
for (const filename of allFiles) {
  const relative = path.relative(projectRoot, filename).replaceAll(path.sep, '/');
  if (/\.py[co]?$/iu.test(relative) || /(^|\/)(?:requirements(?:[-_.][^/]*)?\.txt|Pipfile(?:\.lock)?|pyproject\.toml|render\.ya?ml|Procfile|Dockerfile(?:\.[^/]*)?)$/iu.test(relative) || /(^|\/)supabase\//iu.test(relative)) {
    failures.push(`${relative}: старый Python/Render/Supabase/server deployment asset не относится к этому проекту.`);
  }
}

const runtimeFiles = allFiles.filter(filename => filename.startsWith(`${runtimeRoot}${path.sep}`) && filename.endsWith('.js'));
const runtimeSet = new Set(runtimeFiles.map(filename => path.resolve(filename)));
const operatorFile = path.join(runtimeRoot, 'lib', 'operator-config.js');
let generatedConfig = false;
for (const filename of runtimeFiles) {
  const relative = path.relative(projectRoot, filename).replaceAll(path.sep, '/');
  const modulePath = path.relative(runtimeRoot, filename).replaceAll(path.sep, '/');
  if (modulePath !== 'schema.js' && !/^lib\/.+\.js$/u.test(modulePath) && !/^(handlers|endpoints)\/[^/]+\.js$/u.test(modulePath)) {
    failures.push(`${relative}: модуль не входит в deploy layout Telegram Serverless.`);
  }
  const source = await readFile(filename, 'utf8');
  if (filename === operatorFile) generatedConfig = source.includes('GENERATED_OPERATOR_CONFIG');
  const syntax = spawnSync(process.execPath, ['--check', filename], { encoding: 'utf8', timeout: 10000 });
  if (syntax.error || syntax.status !== 0) { failures.push(`${relative}: синтаксическая ошибка JavaScript.`); continue; }
  const inspected = spawnSync(process.execPath, ['--no-warnings', '--experimental-vm-modules', '--input-type=module', '-e', importInspector], {
    input: source, encoding: 'utf8', timeout: 10000,
  });
  if (inspected.error || inspected.status !== 0) { failures.push(`${relative}: не удалось проверить ES module imports.`); continue; }
  for (const specifier of JSON.parse(inspected.stdout)) {
    if (allowedSdkModules.has(specifier)) continue;
    if (!specifier.startsWith('./') && !specifier.startsWith('../')) {
      failures.push(`${relative}: импорт ${specifier} запрещен; доступны только sdk и относительные .js модули.`); continue;
    }
    if (!specifier.endsWith('.js') || specifier.includes('?') || specifier.includes('#') || specifier.includes('\\')) {
      failures.push(`${relative}: относительный импорт должен оканчиваться на .js.`); continue;
    }
    const resolved = path.resolve(path.dirname(filename), specifier);
    const fromRoot = path.relative(runtimeRoot, resolved);
    if (fromRoot.startsWith('..') || path.isAbsolute(fromRoot)) {
      failures.push(`${relative}: импорт выходит за tgcloud/.`); continue;
    }
    if (!runtimeSet.has(resolved)) {
      if (resolved === operatorFile) warnings.push(`${relative}: operator-config.js еще не создан; запустите npm run configure перед deploy.`);
      else failures.push(`${relative}: отсутствует импортируемый модуль ${specifier}.`);
    }
  }
  const tokens = codeTokens(source);
  const identifiers = new Set(tokens);
  for (const name of forbiddenGlobals) if (identifiers.has(name)) failures.push(`${relative}: ${name} отсутствует в поддерживаемом runtime.`);
  // Dynamic imports hide dependencies from the deploy graph and are unnecessary
  // for this small bot. Keep all modules explicit and auditable.
  const tokenSource = tokens.join(' ');
  if (/\bimport\s*\(/u.test(tokenSource)) failures.push(`${relative}: динамический import не разрешен в этом проекте.`);
  if (/\b(?:db\s*\.\s*(?:transaction|batch)|sdk\s*\.\s*(?:secrets|schedule)|ctx\s*\.\s*env)\b/u.test(tokenSource)) {
    failures.push(`${relative}: использован API, отсутствующий в проверенной документации SDK.`);
  }
}

if (!runtimeSet.has(path.join(runtimeRoot, 'schema.js'))) failures.push('Нет tgcloud/schema.js.');
if (!generatedConfig) warnings.push('Локальные настройки оператора еще не сгенерированы. Безопасный шаблон не включает продажи; перед deploy запустите npm run configure.');
for (const warning of [...new Set(warnings)]) console.warn(`WARN: ${warning}`);
for (const failure of failures) console.error(`ERROR: ${failure}`);
if (failures.length) {
  console.error(`Проверка runtime не пройдена: ${failures.length} ошибок.`);
  process.exitCode = 1;
} else console.log(`Runtime проверен: ${runtimeFiles.length} JS модулей, синтаксис и граф импортов корректны. Облачное выполнение не проверялось.`);
