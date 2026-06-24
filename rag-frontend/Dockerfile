# Cortex admin UI (cortex-web): vite build → static, served by nginx.
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
# VITE_API_URL is baked at build time. Defaults to http://localhost:8002,
# which the browser reaches via the backend's published host port.
ARG VITE_API_URL=http://localhost:8002
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build

FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
