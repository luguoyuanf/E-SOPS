FROM public.ecr.aws/docker/library/node:24-alpine AS base

ENV PNPM_HOME="/pnpm"
ENV PATH="$PNPM_HOME:$PATH"
ENV npm_config_workspace_concurrency=2
ENV npm_config_child_concurrency=2

RUN corepack enable

WORKDIR /app

COPY ./frontend/package.json ./frontend/pnpm-lock.yaml ./frontend/pnpm-workspace.yaml ./frontend/.npmrc ./
COPY ./frontend/apps ./apps
COPY ./frontend/internal ./internal
COPY ./frontend/packages ./packages
COPY ./frontend/scripts ./scripts
COPY ./frontend/vitest.config.ts ./frontend/turbo.json ./

RUN pnpm install --frozen-lockfile

FROM base AS development

EXPOSE 5173

CMD ["pnpm", "-F", "@vben/web-antd", "run", "dev", "--host", "0.0.0.0"]

FROM base AS build

COPY ./artifacts/esop/build-manifest.ts ./apps/web-antd/src/modules/build-manifest.ts

ARG VITE_GLOB_API_URL=/api/v1
ENV VITE_GLOB_API_URL=$VITE_GLOB_API_URL

RUN printf 'VITE_GLOB_API_URL=%s\n' "$VITE_GLOB_API_URL" > .env.production \
    && printf 'VITE_GLOB_API_URL=%s\nVITE_APP_TITLE=ESOPS\nVITE_APP_NAMESPACE=esops-open\nVITE_APP_VERSION=0.1.0\nVITE_PUBLIC_PATH=/\nVITE_ROUTER_HISTORY=history\nVITE_PWA=false\n' "$VITE_GLOB_API_URL" > apps/web-antd/.env.production \
    && pnpm -F @vben/web-antd run build

FROM public.ecr.aws/docker/library/nginx:alpine AS production

COPY ./frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/apps/web-antd/dist /usr/share/nginx/html

EXPOSE 80
