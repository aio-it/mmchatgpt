#!/bin/bash
find . -type f -name '*.py' -or -name "Pipfile*" | entr -zr sh -c 'make dev'
