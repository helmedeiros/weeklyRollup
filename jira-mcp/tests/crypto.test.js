/**
 * Unit tests for crypto.js
 */

describe('crypto module', () => {
  let crypto;
  const TEST_KEY = 'a'.repeat(64); // 64 hex chars = 32 bytes

  beforeEach(() => {
    jest.resetModules();
    process.env.TOKEN_ENCRYPTION_KEY = TEST_KEY;
    crypto = require('../src/crypto');
  });

  afterEach(() => {
    delete process.env.TOKEN_ENCRYPTION_KEY;
  });

  describe('encrypt and decrypt', () => {
    it('should encrypt and decrypt a string correctly', () => {
      const plaintext = 'Hello, World!';
      const encrypted = crypto.encrypt(plaintext);
      const decrypted = crypto.decrypt(encrypted);

      expect(decrypted).toBe(plaintext);
    });

    it('should encrypt and decrypt JSON data', () => {
      const data = { user: 'test@example.com', token: 'secret123' };
      const plaintext = JSON.stringify(data);
      const encrypted = crypto.encrypt(plaintext);
      const decrypted = JSON.parse(crypto.decrypt(encrypted));

      expect(decrypted).toEqual(data);
    });

    it('should produce different ciphertext for same plaintext (random IV)', () => {
      const plaintext = 'test data';
      const encrypted1 = crypto.encrypt(plaintext);
      const encrypted2 = crypto.encrypt(plaintext);

      expect(encrypted1).not.toBe(encrypted2);
    });

    it('should encrypt to format iv:authTag:ciphertext', () => {
      const plaintext = 'test';
      const encrypted = crypto.encrypt(plaintext);
      const parts = encrypted.split(':');

      expect(parts).toHaveLength(3);
      // IV should be base64 encoded (16 bytes -> ~24 chars)
      expect(parts[0].length).toBeGreaterThan(0);
      // Auth tag should be base64 encoded
      expect(parts[1].length).toBeGreaterThan(0);
      // Ciphertext should be base64 encoded
      expect(parts[2].length).toBeGreaterThan(0);
    });

    it('should handle empty string', () => {
      const plaintext = '';
      const encrypted = crypto.encrypt(plaintext);
      const decrypted = crypto.decrypt(encrypted);

      expect(decrypted).toBe('');
    });

    it('should handle unicode characters', () => {
      const plaintext = '日本語 🎉 émojis';
      const encrypted = crypto.encrypt(plaintext);
      const decrypted = crypto.decrypt(encrypted);

      expect(decrypted).toBe(plaintext);
    });

    it('should handle large data', () => {
      const plaintext = 'x'.repeat(100000);
      const encrypted = crypto.encrypt(plaintext);
      const decrypted = crypto.decrypt(encrypted);

      expect(decrypted).toBe(plaintext);
    });
  });

  describe('decrypt error handling', () => {
    it('should throw error for invalid format (missing parts)', () => {
      expect(() => crypto.decrypt('invalid')).toThrow('Invalid encrypted value format');
    });

    it('should throw error for invalid format (too many parts)', () => {
      expect(() => crypto.decrypt('a:b:c:d')).toThrow('Invalid encrypted value format');
    });

    it('should throw error for tampered ciphertext', () => {
      const plaintext = 'test';
      const encrypted = crypto.encrypt(plaintext);
      const parts = encrypted.split(':');
      parts[2] = 'tampered' + parts[2];
      const tampered = parts.join(':');

      expect(() => crypto.decrypt(tampered)).toThrow();
    });

    it('should throw error for tampered auth tag', () => {
      const plaintext = 'test';
      const encrypted = crypto.encrypt(plaintext);
      const parts = encrypted.split(':');
      parts[1] = Buffer.from('wrongtag12345678').toString('base64');
      const tampered = parts.join(':');

      expect(() => crypto.decrypt(tampered)).toThrow();
    });
  });

  describe('encryption key validation', () => {
    it('should throw error when TOKEN_ENCRYPTION_KEY is not set', () => {
      delete process.env.TOKEN_ENCRYPTION_KEY;
      jest.resetModules();
      const cryptoNoKey = require('../src/crypto');

      expect(() => cryptoNoKey.encrypt('test')).toThrow('TOKEN_ENCRYPTION_KEY environment variable is required');
    });

    it('should throw error when TOKEN_ENCRYPTION_KEY is wrong length', () => {
      process.env.TOKEN_ENCRYPTION_KEY = 'tooshort';
      jest.resetModules();
      const cryptoShortKey = require('../src/crypto');

      expect(() => cryptoShortKey.encrypt('test')).toThrow('TOKEN_ENCRYPTION_KEY must be 64 hex characters');
    });
  });

  describe('generateKey', () => {
    it('should generate a 64-character hex key', () => {
      const key = crypto.generateKey();

      expect(key).toHaveLength(64);
      expect(/^[0-9a-f]+$/.test(key)).toBe(true);
    });

    it('should generate unique keys', () => {
      const key1 = crypto.generateKey();
      const key2 = crypto.generateKey();

      expect(key1).not.toBe(key2);
    });
  });

  describe('hash', () => {
    it('should return SHA-256 hash as hex string', () => {
      const result = crypto.hash('test');

      expect(result).toHaveLength(64);
      expect(/^[0-9a-f]+$/.test(result)).toBe(true);
    });

    it('should return consistent hash for same input', () => {
      const hash1 = crypto.hash('test');
      const hash2 = crypto.hash('test');

      expect(hash1).toBe(hash2);
    });

    it('should return different hash for different input', () => {
      const hash1 = crypto.hash('test1');
      const hash2 = crypto.hash('test2');

      expect(hash1).not.toBe(hash2);
    });

    it('should hash known value correctly', () => {
      // SHA-256 of "test" is well-known
      const expected = '9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08';
      expect(crypto.hash('test')).toBe(expected);
    });
  });

  describe('generateToken', () => {
    it('should generate 64-character hex token by default (32 bytes)', () => {
      const token = crypto.generateToken();

      expect(token).toHaveLength(64);
      expect(/^[0-9a-f]+$/.test(token)).toBe(true);
    });

    it('should generate token with custom byte length', () => {
      const token = crypto.generateToken(16);

      expect(token).toHaveLength(32); // 16 bytes = 32 hex chars
    });

    it('should generate unique tokens', () => {
      const token1 = crypto.generateToken();
      const token2 = crypto.generateToken();

      expect(token1).not.toBe(token2);
    });
  });
});
