import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { globalIgnores } from 'eslint/config'

export default tseslint.config([
  globalIgnores([
    '**/node_modules/**',
    '**/.git/**',
    '**/.venv/**',
    '**/venv/**',
    '**/__pycache__/**',
    '**/staticfiles/**',
    '**/dist/**',
    '**/build/**',
    '**/coverage/**',
    '**/*backup*/**',
    '**/*backup*',
    '**/*~',
    '**/*.bak',
    '**/*.orig',
    '**/*.save',
    '**/*.tmp',
  ]),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs['recommended-latest'],
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
  },
])
