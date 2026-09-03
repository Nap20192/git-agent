package consumer

type Option func(*consumer)

func ExchangeName(exchangeName string) Option {
	return func(c *consumer) {
		c.exchangeName = exchangeName
	}
}

func ExchangeKind(exchangeKind string) Option {
	return func(c *consumer) {
		c.exchangeKind = exchangeKind
	}
}

func QueueName(queueName string) Option {
	return func(c *consumer) {
		c.queueName = queueName
	}
}

func BindingKey(bindingKey string) Option {
	return func(c *consumer) {
		c.bindingKey = bindingKey
	}
}

func ConsumerTag(consumerTag string) Option {
	return func(c *consumer) {
		c.consumerTag = consumerTag
	}
}

func WorkerPoolSize(workerPoolSize int) Option {
	return func(c *consumer) {
		c.workerPoolSize = workerPoolSize
	}
}
