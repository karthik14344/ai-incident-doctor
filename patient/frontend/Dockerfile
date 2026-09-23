# KnowledgeAI frontend. Build from the repository root:
#   docker build -f patient/frontend/Dockerfile .
FROM node:20-alpine AS build
WORKDIR /src
COPY patient/frontend/package.json patient/frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY patient/frontend/ ./
# vite.config.js requires GATEWAY_URL for the dev proxy; the production bundle
# only uses relative /api paths, so any value will do at build time.
RUN GATEWAY_URL=http://gateway-upstream npm run build

FROM nginxinc/nginx-unprivileged:1.29-alpine
COPY --from=build /src/dist /usr/share/nginx/html
COPY patient/frontend/nginx.conf.template /etc/nginx/templates/default.conf.template
ARG APP_GIT_SHA=unknown
ENV APP_GIT_SHA=${APP_GIT_SHA}
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --retries=3 CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
