FROM oven/bun:alpine AS builder

WORKDIR /app

# Copy dependency files
COPY package.json bun.lock ./

# Install dependencies using standard bun install
RUN bun install --frozen-lockfile

# Copy the rest of the frontend source
COPY . .

# Build Next.js application
RUN bun run build

# Serve stage (very lightweight)
FROM nginx:alpine

# Copy static HTML export from builder stage to Nginx default html folder
COPY --from=builder /app/out /usr/share/nginx/html

# Copy Nginx configuration for SPA routing and API proxying
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Expose port 80
EXPOSE 80

# Start nginx
CMD ["nginx", "-g", "daemon off;"]
