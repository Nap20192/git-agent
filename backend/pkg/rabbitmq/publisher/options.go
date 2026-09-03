package publisher

type Option func(*publisher)

func ExchangeName(exchangeName string) Option {
	return func(p *publisher) {
		p.exchangeName = exchangeName
	}
}

func ExchangeKind(exchangeKind string) Option {
	return func(p *publisher) {
		p.exchangeKind = exchangeKind
	}
}

func MessageTypeName(messageTypeName string) Option {
	return func(p *publisher) {
		p.messageTypeName = messageTypeName
	}
}
