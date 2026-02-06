FROM node:18-alpine

# Create non-root user for security
RUN addgroup -S appgroup && adduser -S appuser -G appgroup

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm install

COPY . .

# Switch to non-root user
USER appuser

CMD ["npm", "run", "dev"]
