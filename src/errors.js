export class ConfigError extends Error {
  constructor(message) {
    super(message);
    this.name = 'ConfigError';
  }
}

export class UsageError extends Error {
  constructor(message) {
    super(message);
    this.name = 'UsageError';
  }
}
