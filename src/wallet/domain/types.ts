export type AccountType =
  | 'PLAYER_REAL'
  | 'PLAYER_BONUS'
  | 'SYSTEM_DEPOSIT'
  | 'SYSTEM_PAYOUT'
  | 'SYSTEM_HOUSE';

export type TransactionKind =
  | 'DEPOSIT'
  | 'WITHDRAWAL'
  | 'BET'
  | 'WIN'
  | 'BONUS_GRANT'
  | 'BONUS_CONVERT';

export type BonusStatus = 'ACTIVE' | 'COMPLETED' | 'FORFEITED';

export interface Account {
  id: string;
  playerId: string | null;
  type: AccountType;
  currency: string;
}

/**
 * One side of a double-entry transaction: a signed delta applied to one
 * account. The entries of a single transaction must sum to zero.
 */
export interface LedgerEntryDraft {
  accountId: string;
  amount: bigint;
}

export interface Bonus {
  id: string;
  playerId: string;
  currency: string;
  grantedAmount: bigint;
  wageringMultiplier: number;
  wageringRequired: bigint;
  wageringProgress: bigint;
  status: BonusStatus;
}

export interface BalanceView {
  playerId: string;
  currency: string;
  /** Withdrawable money, in minor units. */
  real: string;
  /** Bonus money, locked until wagering completes. */
  bonus: string;
  /** real + bonus. */
  total: string;
  wagering: {
    required: string;
    progress: string;
    remaining: string;
  } | null;
}

export interface OperationResult {
  transactionId: string;
  kind: TransactionKind;
  /** True when this response was replayed from a previous identical request. */
  replayed: boolean;
  balance: BalanceView;
}

/** One operation as the audit trail shows it: its legs, and what they sum to. */
export interface TransactionView {
  /** Monotonic insertion order — the correct way to read the log. */
  seq: number;
  kind: TransactionKind;
  reference: string | null;
  createdAt: string;
  entries: { account: AccountType; amount: string }[];
}
