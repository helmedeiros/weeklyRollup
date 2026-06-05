/**
 * Unit tests for index.js (MCP Server)
 */

// Mock the MCP SDK before requiring the module
jest.mock('@modelcontextprotocol/sdk/server/index.js', () => ({
  Server: jest.fn().mockImplementation(() => ({
    setRequestHandler: jest.fn(),
    connect: jest.fn().mockResolvedValue(undefined)
  }))
}));

jest.mock('@modelcontextprotocol/sdk/server/stdio.js', () => ({
  StdioServerTransport: jest.fn()
}));

jest.mock('@modelcontextprotocol/sdk/types.js', () => ({
  CallToolRequestSchema: 'CallToolRequestSchema',
  ListToolsRequestSchema: 'ListToolsRequestSchema'
}));

jest.mock('../src/tools', () => ({
  TOOLS: [
    { name: 'test_tool', description: 'A test tool', inputSchema: { type: 'object', properties: {} } }
  ],
  handleToolCall: jest.fn()
}));

describe('MCP Server (index.js)', () => {
  let Server;
  let StdioServerTransport;
  let tools;
  let mockServer;

  beforeEach(() => {
    jest.resetModules();
    jest.clearAllMocks();

    // Suppress console output
    jest.spyOn(console, 'log').mockImplementation();
    jest.spyOn(console, 'error').mockImplementation();

    Server = require('@modelcontextprotocol/sdk/server/index.js').Server;
    StdioServerTransport = require('@modelcontextprotocol/sdk/server/stdio.js').StdioServerTransport;
    tools = require('../src/tools');

    // Get the mock server instance
    mockServer = {
      setRequestHandler: jest.fn(),
      connect: jest.fn().mockResolvedValue(undefined)
    };
    Server.mockImplementation(() => mockServer);
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  describe('Server initialization', () => {
    it('should create Server with correct name and version', () => {
      // Require the module to trigger initialization
      jest.isolateModules(() => {
        require('../src/index');
      });

      expect(Server).toHaveBeenCalledWith(
        {
          name: 'jira-mcp',
          version: '1.4.2'
        },
        {
          capabilities: {
            tools: {}
          }
        }
      );
    });

    it('should register ListToolsRequestSchema handler', () => {
      jest.isolateModules(() => {
        require('../src/index');
      });

      expect(mockServer.setRequestHandler).toHaveBeenCalledWith(
        'ListToolsRequestSchema',
        expect.any(Function)
      );
    });

    it('should register CallToolRequestSchema handler', () => {
      jest.isolateModules(() => {
        require('../src/index');
      });

      expect(mockServer.setRequestHandler).toHaveBeenCalledWith(
        'CallToolRequestSchema',
        expect.any(Function)
      );
    });
  });

  describe('ListToolsRequestSchema handler', () => {
    it('should return tools array', async () => {
      let listHandler;

      mockServer.setRequestHandler.mockImplementation((schema, handler) => {
        if (schema === 'ListToolsRequestSchema') {
          listHandler = handler;
        }
      });

      jest.isolateModules(() => {
        require('../src/index');
      });

      const result = await listHandler();

      expect(result).toEqual({
        tools: [
          { name: 'test_tool', description: 'A test tool', inputSchema: { type: 'object', properties: {} } }
        ]
      });
    });
  });

  describe('CallToolRequestSchema handler', () => {
    let callHandler;

    beforeEach(() => {
      mockServer.setRequestHandler.mockImplementation((schema, handler) => {
        if (schema === 'CallToolRequestSchema') {
          callHandler = handler;
        }
      });

      jest.isolateModules(() => {
        require('../src/index');
      });
    });

    it('should call handleToolCall with name and args', async () => {
      tools.handleToolCall.mockResolvedValue({ success: true });

      const request = {
        params: {
          name: 'test_tool',
          arguments: { key: 'value' }
        }
      };

      await callHandler(request);

      expect(tools.handleToolCall).toHaveBeenCalledWith('test_tool', { key: 'value' });
    });

    it('should handle missing arguments', async () => {
      tools.handleToolCall.mockResolvedValue({ success: true });

      const request = {
        params: {
          name: 'test_tool'
        }
      };

      await callHandler(request);

      expect(tools.handleToolCall).toHaveBeenCalledWith('test_tool', {});
    });

    it('should return formatted success response', async () => {
      tools.handleToolCall.mockResolvedValue({ result: 'data' });

      const request = {
        params: {
          name: 'test_tool',
          arguments: {}
        }
      };

      const result = await callHandler(request);

      expect(result).toEqual({
        content: [
          {
            type: 'text',
            text: JSON.stringify({ result: 'data' }, null, 2)
          }
        ]
      });
    });

    it('should return error response for failed tool call', async () => {
      tools.handleToolCall.mockRejectedValue(new Error('Tool failed'));

      const request = {
        params: {
          name: 'test_tool',
          arguments: {}
        }
      };

      const result = await callHandler(request);

      expect(result).toEqual({
        content: [
          {
            type: 'text',
            text: 'Error: Tool failed'
          }
        ],
        isError: true
      });
    });

    it('should extract error message from Axios response', async () => {
      const axiosError = new Error('Request failed');
      axiosError.response = {
        data: {
          errorMessages: ['Invalid project key', 'Project not found']
        }
      };
      tools.handleToolCall.mockRejectedValue(axiosError);

      const request = {
        params: {
          name: 'test_tool',
          arguments: {}
        }
      };

      const result = await callHandler(request);

      expect(result.content[0].text).toBe('Error: Invalid project key, Project not found');
    });

    it('should extract error message from Atlassian API response', async () => {
      const apiError = new Error('API Error');
      apiError.response = {
        data: {
          message: 'Unauthorized'
        }
      };
      tools.handleToolCall.mockRejectedValue(apiError);

      const request = {
        params: {
          name: 'test_tool',
          arguments: {}
        }
      };

      const result = await callHandler(request);

      expect(result.content[0].text).toBe('Error: Unauthorized');
    });
  });
});
