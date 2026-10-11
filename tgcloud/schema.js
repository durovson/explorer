import { table, integer, text, json, index, check, sql } from 'sdk/db';

// No foreign keys: the platform explicitly disables them. Store methods enforce ownership.
export const users = table('users', {
  id: integer('id').primaryKey(),
  username: text('username'),
  firstName: text('first_name').notNull(),
  languageCode: text('language_code').notNull().default('ru'),
  referrerId: integer('referrer_id'),
  createdAt: integer('created_at').notNull(),
  updatedAt: integer('updated_at').notNull(),
}, (t) => ({ referrerIdx: index('users_referrer_idx').on(t.referrerId) }));

export const sessions = table('sessions', {
  userId: integer('user_id').primaryKey(),
  state: text('state').notNull(),
  data: json('data').notNull(),
  updatedAt: integer('updated_at').notNull(),
});

export const orders = table('orders', {
  id: integer('id').primaryKey({ autoIncrement: true }),
  userId: integer('user_id').notNull(),
  recipient: text('recipient').notNull(),
  product: text('product').notNull(),
  quantity: integer('quantity').notNull(),
  currency: text('currency').notNull(),
  // Atomic currency amounts are TEXT: SQLite INTEGER and JS Number have different limits.
  amountAtomic: text('amount_atomic').notNull(),
  baseAtomic: text('base_atomic').notNull(),
  markupAtomic: text('markup_atomic').notNull(),
  providerFeeAtomic: text('provider_fee_atomic').notNull(),
  markupBps: integer('markup_bps').notNull(),
  walletAddress: text('wallet_address').notNull(),
  // NULL only between allocation and memo persistence. Such rows cannot accept payment.
  memo: text('memo').unique(),
  creationKey: text('creation_key').notNull().unique(),
  status: text('status').notNull().default('WAITING_PAYMENT'),
  txHash: text('tx_hash').unique(),
  txLt: text('tx_lt'),
  sender: text('sender'),
  externalId: text('external_id').unique(),
  attemptAt: integer('attempt_at'),
  paidAt: integer('paid_at'),
  completedAt: integer('completed_at'),
  createdAt: integer('created_at').notNull(),
  expiresAt: integer('expires_at').notNull(),
  updatedAt: integer('updated_at').notNull(),
  chatId: integer('chat_id'),
  messageId: integer('message_id'),
  error: text('error'),
  providerResponse: json('provider_response'),
}, (t) => ({
  ownerIdx: index('orders_owner_idx').on(t.userId, t.createdAt),
  statusIdx: index('orders_status_idx').on(t.status, t.createdAt),
  statusCheck: check('orders_status_check', sql.raw("status IN ('WAITING_PAYMENT','PAID','FULFILLING','COMPLETED','REVIEW','FAILED','CANCELLED','EXPIRED')")),
  productCheck: check('orders_product_check', sql.raw("(product = 'STARS' AND quantity BETWEEN 50 AND 1000000) OR (product = 'PREMIUM' AND quantity IN (3,6,12))")),
  currencyCheck: check('orders_currency_check', sql.raw("currency IN ('TON','USDT')")),
  windowCheck: check('orders_window_check', sql.raw('expires_at > created_at')),
}));
