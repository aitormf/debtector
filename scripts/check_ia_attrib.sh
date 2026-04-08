#!/bin/sh

MSG=$(cat "$1")

# Block commits with AI attribution lines in the commit message.
# Catches: Co-Authored-By: Claude, Generated with Claude Code, noreply@anthropic.com
# Does NOT block casual mentions of tools in descriptions.
BLOCKED_PATTERNS="Co-Authored-By:.*[Cc]laude|Co-Authored-By:.*[Aa]nthropic|Generated with \[?Claude|noreply@anthropic\.com"

if echo "$MSG" | grep -qE "$BLOCKED_PATTERNS"; then
  echo "\033[0;31m❌ Commit bloqueado: el mensaje contiene atribuciones a herramientas de IA\033[0m"
  echo "\033[1;33m💡 Elimina las líneas Co-Authored-By / Generated with del mensaje\033[0m"
  echo ""
  echo "Líneas problemáticas:"
  echo "$MSG" | grep -nE "$BLOCKED_PATTERNS" | sed 's/^/  /'
  exit 1
fi
