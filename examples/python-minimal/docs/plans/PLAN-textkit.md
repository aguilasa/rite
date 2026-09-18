# Plan — textkit

## 1. Context

A tiny library used to exercise the Rite workflow end to end.

## 2. Functions

### 2.1 slugify

`textkit.slugify(text: str) -> str`: lower-case ASCII, runs of non-alphanumeric characters become a
single `-`, no leading or trailing `-`. `slugify("Hello, World!") == "hello-world"`.

### 2.2 word count

`python -m textkit.count <file>` prints the number of whitespace-separated words in the file.
For `data/golden/words.txt` it prints `42`.

## 3. Verification

`python -m unittest discover -s tests` is green.
