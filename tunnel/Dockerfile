FROM golang:1.25-alpine AS build
WORKDIR /src
COPY . .
RUN CGO_ENABLED=0 go build -o /relay ./cmd/relay

FROM scratch
COPY --from=build /relay /relay
ENTRYPOINT ["/relay"]
