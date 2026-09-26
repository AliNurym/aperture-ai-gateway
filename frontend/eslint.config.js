import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{js,jsx}'],
    extends: [
      js.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
      parserOptions: {
        ecmaVersion: 'latest',
        ecmaFeatures: { jsx: true },
        sourceType: 'module',
      },
    },
    rules: {
      // This prototype deliberately uses polling effects to synchronize
      // gateway telemetry. Enforce hook dependencies, but do not apply the
      // experimental React Compiler's synchronous-effect heuristic yet.
      'react-hooks/set-state-in-effect': 'off',
      'react-refresh/only-export-components': 'off',
      'no-empty': ['error', { allowEmptyCatch: true }],
      'no-unused-vars': ['warn', {
        varsIgnorePattern: '^[A-Z_]',
        argsIgnorePattern: '^_',
        caughtErrorsIgnorePattern: '^_',
      }],
    },
  },
])
