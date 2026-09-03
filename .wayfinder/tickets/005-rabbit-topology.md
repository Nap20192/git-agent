# Топология RabbitMQ (События)

Type: wayfinder:grilling
Status: open
Assignee:
Blocked by: [Сборки Агентов и реестр раннеров](004-agent-registry.md)

## Question

(Перескоплен: возим События через outbox-паблишер; ack — не гарантия, auto-ack + БД.) Exchange и очереди: одна общая очередь событий с competing consumers или routing (по репо/сборке — задел под профили)? Семантика outbox-паблишера: батч, порядок, пометка published. RabbitMQ добавить в deploy/docker-compose.yml (контейнер git-agent-rabbitmq уже крутится — узнать, откуда он поднят, и закрепить в compose).
