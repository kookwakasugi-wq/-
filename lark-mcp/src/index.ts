#!/usr/bin/env node
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import express from 'express';
import { LarkClient } from './lark.js';
import { createServer } from './server.js';

async function main(): Promise<void> {
  const useHttp = process.argv.includes('--http') || process.env.MCP_TRANSPORT === 'http';
  const client = LarkClient.fromEnv();

  if (!useHttp) {
    const server = createServer(client);
    await server.connect(new StdioServerTransport());
    return;
  }

  const port = Number(process.env.PORT ?? 3000);
  const authToken = process.env.MCP_AUTH_TOKEN;
  const app = express();
  app.use(express.json({ limit: '4mb' }));

  app.get('/healthz', (_req, res) => {
    res.json({ status: 'ok' });
  });

  app.post('/mcp', async (req, res) => {
    if (authToken && req.header('authorization') !== `Bearer ${authToken}`) {
      res.status(401).json({
        jsonrpc: '2.0',
        error: { code: -32001, message: 'Unauthorized' },
        id: null
      });
      return;
    }

    // Stateless: one server + transport per request, so the process can sit
    // behind a load balancer without sticky sessions.
    const server = createServer(client);
    const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined });
    res.on('close', () => {
      void transport.close();
      void server.close();
    });

    try {
      await server.connect(transport);
      await transport.handleRequest(req, res, req.body);
    } catch (error) {
      console.error('Request failed:', error);
      if (!res.headersSent) {
        res.status(500).json({
          jsonrpc: '2.0',
          error: { code: -32603, message: 'Internal server error' },
          id: null
        });
      }
    }
  });

  // GET/DELETE on /mcp are only meaningful for session-based servers.
  const rejectSessionMethods = (_req: express.Request, res: express.Response): void => {
    res.status(405).json({
      jsonrpc: '2.0',
      error: { code: -32000, message: 'Method not allowed. This server is stateless; use POST /mcp.' },
      id: null
    });
  };
  app.get('/mcp', rejectSessionMethods);
  app.delete('/mcp', rejectSessionMethods);

  app.listen(port, () => {
    console.error(`lark-mcp listening on http://0.0.0.0:${port}/mcp`);
    if (!authToken) {
      console.error('WARNING: MCP_AUTH_TOKEN is unset — the endpoint is unauthenticated.');
    }
  });
}

main().catch(error => {
  console.error(error instanceof Error ? error.message : error);
  process.exit(1);
});
