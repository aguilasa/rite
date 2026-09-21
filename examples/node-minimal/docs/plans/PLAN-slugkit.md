# Plan — slugkit

## 1. Context

A tiny Node library used to exercise the Rite workflow end to end on a non-Python stack.

## 2. Functions

### 2.1 slugify

`slugify(text)` exported from `src/slug.mjs`: lower-case ASCII, runs of non-alphanumeric characters
become a single `-`, no leading or trailing `-`. `slugify("Hello, World!") === "hello-world"`.

Every module added to `src/` is re-exported from `src/index.mjs` by `tools/gen-exports.mjs`.

### 2.2 word count

`node bin/wc.mjs <file>` prints the number of whitespace-separated words in the file. For
`fixtures/golden/words.txt` it prints `42`. The counting itself lives in `src/count.mjs` as
`countWords(text)`.

## 3. Verification

`npm test` is green and `node tools/gen-exports.mjs --check` passes.
