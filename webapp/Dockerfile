# Docker's official images, from Google's Docker Hub mirror (mirror.gcr.io), as the database image and the CI's
# BuildKit: Docker Hub limits anonymous pulls by address, and Amazon ECR Public's mirror ran out of data for
# the shared runners too (429). The same images, by the same digests.
FROM mirror.gcr.io/library/node:20-slim AS build

LABEL org.opencontainers.image.source="https://github.com/infn-argus/argus-knowledge-hub"
LABEL org.opencontainers.image.description="ARGUS Knowledge Hub — operator and admin web UI"
LABEL org.opencontainers.image.licenses="INFN"

WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
# Which identity provider the "INFN login" button talks to, and where the API is.
# Baked in at build time (this is a static bundle); left unset, the button is
# simply not offered, which is what the production build wants until it is told.
ARG VITE_OIDC_AUTHORITY
ARG VITE_OIDC_CLIENT_ID
ARG VITE_OIDC_LABEL
ARG VITE_API_BASE_URL
# Which release this is, set by the release workflow and shown on the About page.
ARG VITE_APP_VERSION=dev
ARG VITE_APP_COMMIT=
ARG VITE_APP_BUILT_AT=
ENV VITE_APP_VERSION=$VITE_APP_VERSION \
    VITE_APP_COMMIT=$VITE_APP_COMMIT \
    VITE_APP_BUILT_AT=$VITE_APP_BUILT_AT
ENV VITE_OIDC_AUTHORITY=$VITE_OIDC_AUTHORITY \
    VITE_OIDC_CLIENT_ID=$VITE_OIDC_CLIENT_ID \
    VITE_OIDC_LABEL=$VITE_OIDC_LABEL \
    VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

FROM mirror.gcr.io/library/nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 8080
