FROM golang:1.27-alpine AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -o /hub ./cmd/hub

FROM alpine:3.21
COPY --from=build /hub /hub
EXPOSE 8081
ENTRYPOINT ["/hub"]
