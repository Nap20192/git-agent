# Топология RabbitMQ (События)

Type: wayfinder:grilling
Status: closed
Assignee: vnkjd
Blocked by: [Сборки Агентов и реестр раннеров](004-agent-registry.md)

## Question

Exchange и очереди, семантика outbox-паблишера, RabbitMQ в deploy.

## Answer

- **Свой Rabbit в deploy/docker-compose.yml**: rabbitmq:4-management, хост-порты **5673** (AMQP) и **15673** (management) — 5672 занят контейнером соседнего проекта ais (`git-agent-rabbitmq` — он не наш, не завязываемся).
- **Topic exchange `events`** + одна durable-очередь, бинд `#`, все раннеры — competing consumers. Routing key `provider.repo.action` — профили потом добавляются новыми биндами без переделки публикации.
- **Доставка**: persistent-сообщения; outbox-паблишер поллит батчами по порядку id, помечает `published_at` только после publisher confirm — at-least-once, дубли гасит дедуп Экземпляра (журнал обработанных Событий).
- **Ре-публикация**: backend-воркер по протухшему heartbeat переводит Экземпляры раннера в `down`, События без отметки «обработано» уходят в outbox заново.
