# Proposal: add-agent-mode-http

## Why

Агентный режим (Лид + Сабагенты) доступен только из CLI: gateway держит один Runtime с pipeline-профилем, и сабмит из UI всегда создаёт pipeline-Ран. Пользователь хочет запускать Лида из интерфейса и видеть звезду делегирований на графе.

## What Changes

- Gateway держит по Runtime на режим (pipeline и agent) над общими store/bridge; `POST /runs` принимает `mode` (дефолт pipeline) и маршрутизирует submit.
- Resume маршрутизируется по фактическому режиму Рана (агентность видна по событиям), не по дефолту.
- UI: переключатель режима в форме нового Рана; openapi.yaml дополнен полем `mode`.

## Capabilities

### New Capabilities

(нет)

### Modified Capabilities

- `http-gateway`: submit принимает режим Рана; снятие ограничения «только pipeline».

## Impact

- `server/app.py` (два Runtime, маршрутизация), `frontend/docs/openapi.yaml`, `frontend/src` (contract + форма). Идентичность Рана по-прежнему не включает режим — кросс-режимный resubmit присоединяется к существующему Рану (документировано в durable-runs/agent-graph).
