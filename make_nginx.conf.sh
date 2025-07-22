#!/bin/bash

DOMAIN="$1"

if [ -z "$DOMAIN" ]; then
  echo "❌ Debes pasar el dominio como argumento."
  echo "Uso: ./generar_nginx.sh tu-dominio.com"
  exit 1
fi

cat > nginx.conf <<EOF
events {
    worker_connections 1024;
}

http {
    upstream app_server {
        server web:5080;
    }

    include       mime.types;
    default_type  application/octet-stream;
    charset utf-8;
    charset_types application/json text/plain text/xml text/css application/javascript;

    server {
        listen 80;
        server_name $DOMAIN;

        location /.well-known/acme-challenge/ {
            root /var/www/certbot;
        }

        location / {
            return 301 https://\$host\$request_uri;
        }
    }

    server {
        listen 443 ssl;
        server_name $DOMAIN;

        ssl_certificate /etc/letsencrypt/live/$DOMAIN/fullchain.pem;
        ssl_certificate_key /etc/letsencrypt/live/$DOMAIN/privkey.pem;

        ssl_protocols TLSv1.2 TLSv1.3;
        ssl_ciphers HIGH:!aNULL:!MD5;

        location /css/ {
            alias /usr/share/nginx/html/css/;
            autoindex off;
            add_header Content-Type text/css;
            add_header X-Content-Type-Options "nosniff";
        }

        location /img/ {
            alias /usr/share/nginx/html/img/;
            autoindex off;
        }

        location /js/ {
            alias /usr/share/nginx/html/js/;
            autoindex off;
            add_header Content-Type application/javascript;
            add_header X-Content-Type-Options "nosniff";
        }

        location / {
            proxy_pass http://app_server;
            proxy_set_header Host \$host;
            proxy_set_header X-Real-IP \$remote_addr;
            proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
            proxy_set_header Accept-Encoding "";
            proxy_set_header Accept-Charset "utf-8";
        }
    }
}
EOF

echo "✅ nginx.conf generado para el dominio: $DOMAIN"

