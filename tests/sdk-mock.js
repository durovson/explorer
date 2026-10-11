import { DatabaseSync } from 'node:sqlite';

let sqlite = new DatabaseSync(':memory:');
let fetchImplementation = async () => { throw new Error('Outbound HTTP is disabled in local tests'); };
export const apiCalls = [];
export const api = new Proxy({}, { get: (_, method) => async (params) => {
  apiCalls.push({ method, params });
  if(method==='getMe') return {id:999,is_bot:true,username:'TestShopBot'};
  return { message_id: apiCalls.length, chat: { id: params?.chat_id }, ...params };
} });
export function setFetch(fn) { fetchImplementation = fn; }
export async function fetch(...args) { return fetchImplementation(...args); }
export class EndpointError extends Error { constructor(message, parameters = {}) { super(message); this.parameters = parameters; } }
export class BotApiError extends Error {
  constructor(code,description,method='') { super(description); this.code=code; this.description=description; this.method=method; }
}

export const sql = (parts, ...values) => ({ query: parts.reduce((result, part, i) => result + (i ? String(values[i - 1]) : '') + part, '') });
sql.raw = (query) => ({ query });
function column(type, name) {
  return { type, name, nullable: true, uniqueFlag: false,
    primaryKey(options = {}) { this.primary = true; this.autoIncrement = !!options.autoIncrement; return this; },
    notNull() { this.nullable = false; return this; },
    unique() { this.uniqueFlag = true; return this; },
    default(value) { this.defaultValue = value; return this; },
  };
}
export const integer = (name) => column('INTEGER', name);
export const text = (name) => column('TEXT', name);
export const json = (name) => column('TEXT', name);
export const index = (name) => ({ kind: 'index', name, on(...columns) { this.columns = columns; return this; } });
export const check = (name, expression) => ({ kind: 'check', name, expression });
export function table(name, columns, constraints) {
  return { name, columns, constraints: constraints ? constraints(columns) : {} };
}

const quote = (identifier) => `"${String(identifier).replaceAll('"', '""')}"`;
export function resetDatabase(schema) {
  sqlite.close();
  sqlite = new DatabaseSync(':memory:');
  apiCalls.length = 0;
  fetchImplementation = async () => { throw new Error('Outbound HTTP is disabled in local tests'); };
  for (const descriptor of Object.values(schema)) {
    if (!descriptor?.columns) continue;
    const definitions = Object.entries(descriptor.columns).map(([key, c]) => {
      c.name ||= key;
      let definition = `${quote(c.name)} ${c.type}`;
      if (c.primary) definition += ` PRIMARY KEY${c.autoIncrement ? ' AUTOINCREMENT' : ''}`;
      if (!c.nullable) definition += ' NOT NULL';
      if (c.uniqueFlag) definition += ' UNIQUE';
      if (c.defaultValue !== undefined) definition += typeof c.defaultValue === 'number' ? ` DEFAULT ${c.defaultValue}` : ` DEFAULT '${String(c.defaultValue).replaceAll("'", "''")}'`;
      return definition;
    });
    for (const constraint of Object.values(descriptor.constraints)) {
      if (constraint.kind === 'check') definitions.push(`CONSTRAINT ${quote(constraint.name)} CHECK (${constraint.expression.query})`);
    }
    sqlite.exec(`CREATE TABLE ${quote(descriptor.name)} (${definitions.join(',')})`);
    for (const constraint of Object.values(descriptor.constraints)) {
      if (constraint.kind === 'index') sqlite.exec(`CREATE INDEX ${quote(constraint.name)} ON ${quote(descriptor.name)} (${constraint.columns.map((c) => quote(c.name)).join(',')})`);
    }
  }
}

function prepared(query) { return sqlite.prepare(typeof query === 'string' ? query : query.query); }
export const db = {
  async run(query, parameters = {}) {
    const statement = prepared(query);
    if (/\bRETURNING\b/i.test(typeof query === 'string' ? query : query.query)) {
      const rows = statement.all(parameters);
      return { rowsAffected: rows.length, lastInsertRowid: sqlite.prepare('SELECT last_insert_rowid() AS id').get().id, rows };
    }
    const result = statement.run(parameters);
    return { rowsAffected: Number(result.changes), lastInsertRowid: Number(result.lastInsertRowid), rows: [] };
  },
  async all(query, parameters = {}) { return prepared(query).all(parameters).map((row) => ({ ...row })); },
  async get(query, parameters = {}) { const row = prepared(query).get(parameters); return row ? { ...row } : null; },
};
