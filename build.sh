#!/usr/bin/env bash
# build.sh — Script de build para o Render.com
# Executado automaticamente em cada deploy antes de iniciar o servidor.

set -o errexit  # Aborta se qualquer comando falhar

echo "▶ Instalando dependências..."
pip install -r requirements.txt

echo "▶ Coletando ficheiros estáticos..."
python manage.py collectstatic --noinput

echo "▶ Aplicando migrações..."
python manage.py migrate --noinput

echo "✅ Build concluído com sucesso!"
