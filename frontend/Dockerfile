# Frontend Dockerfile
FROM node:18-alpine

WORKDIR /app

# Copy package files and install
COPY package*.json ./
RUN npm install

# Copy the rest of the code
COPY . .

# Expose the port
EXPOSE 5173

# Run in dev mode for now (or build and serve)
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
