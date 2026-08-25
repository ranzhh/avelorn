FROM node:22-bookworm-slim

WORKDIR /app

# openapi.json comes too: npm ci runs the prepare script, which generates
# the TypeScript from it.
COPY frontend/package.json frontend/package-lock.json frontend/openapi.json ./
RUN npm ci

COPY frontend ./

EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
