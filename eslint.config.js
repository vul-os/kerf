import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist', 'backend/**']),
  {
    files: ['**/*.{js,jsx}'],
    extends: [
      js.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      globals: globals.browser,
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
  },
  {
    // G1 (T-500): TypeScript slices. Deliberately *not* type-aware linting
    // (`recommendedTypeChecked`) yet — that requires a program build per lint run and would
    // report against the un-migrated tree. T-521/T-522 tighten this alongside `strict`.
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      ...tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      globals: globals.browser,
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    rules: {
      // Migration ergonomics: a slice may land an `any` at a boundary it does not own,
      // but must justify it inline. T-521/T-522 flip these to 'error'.
      '@typescript-eslint/no-explicit-any': 'warn',
      // `@ts-ignore` is banned in favour of `@ts-expect-error` with a description, so stale
      // suppressions surface as errors once the underlying issue is fixed.
      '@typescript-eslint/ban-ts-comment': ['error', {
        'ts-ignore': true,
        'ts-expect-error': 'allow-with-description',
      }],
      // Unused vars: allow the `_`-prefix escape hatch used across the JS tree.
      '@typescript-eslint/no-unused-vars': ['error', {
        argsIgnorePattern: '^_',
        varsIgnorePattern: '^_',
      }],
    },
  },
  {
    // Ambient declaration files. Everything in a `.d.ts` is by nature "unused" lexically —
    // `interface Navigator { ... }` is declaration merging against lib.dom, not a dead local.
    // Linting it as an unused var is a false positive, so the rule is off here only.
    files: ['**/*.d.ts'],
    rules: {
      '@typescript-eslint/no-unused-vars': 'off',
      'no-unused-vars': 'off',
    },
  },
  {
    // Vite config runs in Node
    files: ['vite.config.js'],
    languageOptions: { globals: { ...globals.browser, ...globals.node } },
  },
])
