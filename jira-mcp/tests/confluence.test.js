/**
 * Unit tests for confluence.js
 */

// Create a mock function that also has method properties
const mockAxios = jest.fn();
mockAxios.post = jest.fn();
mockAxios.get = jest.fn();
mockAxios.put = jest.fn();
mockAxios.delete = jest.fn();

jest.mock('axios', () => mockAxios);
jest.mock('../src/auth', () => ({
  getValidAccessToken: jest.fn(),
  getCurrentUser: jest.fn()
}));
jest.mock('../src/file-store', () => ({
  init: jest.fn()
}));

const axios = require('axios');

describe('confluence module', () => {
  let ConfluenceAPI;
  let CONFLUENCE_FIELD_SETS;
  let confluence;
  let auth;

  const mockToken = {
    cloud_id: 'test-cloud-id',
    access_token: 'test-access-token',
    site_url: 'https://test.atlassian.net',
    scope: 'read:page:confluence read:space:confluence read:label:confluence search:confluence read:watcher:confluence write:watcher:confluence'
  };

  beforeEach(() => {
    jest.resetModules();
    jest.clearAllMocks();

    const confluenceModule = require('../src/confluence');
    ConfluenceAPI = confluenceModule.ConfluenceAPI;
    CONFLUENCE_FIELD_SETS = confluenceModule.CONFLUENCE_FIELD_SETS;
    confluence = new ConfluenceAPI();

    auth = require('../src/auth');
    auth.getValidAccessToken.mockResolvedValue(mockToken);
    auth.getCurrentUser.mockReturnValue('test@example.com');
  });

  describe('CONFLUENCE_FIELD_SETS', () => {
    it('should have minimal field set with no includes', () => {
      expect(CONFLUENCE_FIELD_SETS.minimal.include).toEqual([]);
      expect(CONFLUENCE_FIELD_SETS.minimal.bodyFormat).toBeNull();
    });

    it('should have standard field set with version', () => {
      expect(CONFLUENCE_FIELD_SETS.standard.include).toContain('version');
    });

    it('should have extended field set with labels and properties', () => {
      expect(CONFLUENCE_FIELD_SETS.extended.include).toContain('labels');
      expect(CONFLUENCE_FIELD_SETS.extended.include).toContain('properties');
    });

    it('should have full field set with body format', () => {
      expect(CONFLUENCE_FIELD_SETS.full.bodyFormat).toBe('storage');
      expect(CONFLUENCE_FIELD_SETS.full.include).toContain('operations');
    });
  });

  describe('getFieldSetConfig', () => {
    it('should return minimal config by default', () => {
      expect(confluence.getFieldSetConfig()).toEqual(CONFLUENCE_FIELD_SETS.minimal);
    });

    it('should return requested field set config', () => {
      expect(confluence.getFieldSetConfig('full')).toEqual(CONFLUENCE_FIELD_SETS.full);
    });

    it('should fallback to minimal for invalid field set', () => {
      expect(confluence.getFieldSetConfig('invalid')).toEqual(CONFLUENCE_FIELD_SETS.minimal);
    });
  });

  describe('init', () => {
    it('should return baseUrl, accessToken, and siteUrl', async () => {
      const result = await confluence.init();

      expect(result.baseUrl).toBe('https://api.atlassian.com/ex/confluence/test-cloud-id/wiki/api/v2');
      expect(result.accessToken).toBe('test-access-token');
      expect(result.siteUrl).toBe('https://test.atlassian.net');
    });
  });

  describe('request', () => {
    it('should force refresh and retry once after a 401 response', async () => {
      mockAxios
        .mockRejectedValueOnce({ response: { status: 401 } })
        .mockResolvedValueOnce({ data: { results: [], _links: {} } });

      const result = await confluence.listSpaces();

      expect(result.spaces).toEqual([]);
      expect(auth.getValidAccessToken).toHaveBeenNthCalledWith(1, 'test@example.com', { forceRefresh: false });
      expect(auth.getValidAccessToken).toHaveBeenNthCalledWith(2, 'test@example.com', { forceRefresh: true });
      expect(mockAxios).toHaveBeenCalledTimes(2);
    });

    it('should raise a clear error when required scopes are missing', async () => {
      auth.getValidAccessToken.mockResolvedValueOnce({
        ...mockToken,
        scope: 'search:confluence'
      });

      await expect(confluence.listPages()).rejects.toThrow(
        'Confluence access token is missing required OAuth scopes: read:page:confluence.'
      );
    });
  });

  describe('Spaces', () => {
    describe('listSpaces', () => {
      it('should return formatted spaces', async () => {
        mockAxios.mockResolvedValueOnce({
          data: {
            results: [
              { id: '1', key: 'SPACE1', name: 'Space 1', type: 'global', status: 'current' },
              { id: '2', key: 'SPACE2', name: 'Space 2', type: 'personal', status: 'current' }
            ],
            _links: { next: '/spaces?cursor=abc123' }
          }
        });

        const result = await confluence.listSpaces();

        expect(result.spaces).toHaveLength(2);
        expect(result.spaces[0]).toEqual({
          id: '1',
          key: 'SPACE1',
          name: 'Space 1',
          type: 'global',
          status: 'current'
        });
        expect(result.hasMore).toBe(true);
        expect(result.nextCursor).toBe('abc123');
      });

      it('should respect limit and type options', async () => {
        mockAxios.mockResolvedValueOnce({
          data: { results: [], _links: {} }
        });

        await confluence.listSpaces({ limit: 10, type: 'global' });

        expect(mockAxios).toHaveBeenCalledWith(
          expect.objectContaining({
            params: expect.objectContaining({
              limit: 10,
              type: 'global'
            })
          })
        );
      });
    });

    describe('getSpace', () => {
      it('should return formatted space details', async () => {
        mockAxios.mockResolvedValueOnce({
          data: {
            id: '1',
            key: 'SPACE',
            name: 'Space',
            type: 'global',
            status: 'current',
            description: { plain: { value: 'A space description' } },
            homepageId: '123',
            createdAt: '2024-01-01'
          }
        });

        const result = await confluence.getSpace('1');

        expect(result.id).toBe('1');
        expect(result.description).toBe('A space description');
        expect(result.homepageId).toBe('123');
      });
    });

    describe('getSpaceByKey', () => {
      it('should search for space by key', async () => {
        mockAxios.mockResolvedValueOnce({
          data: {
            results: [{ id: '1', key: 'SPACE', name: 'Space', type: 'global', status: 'current' }]
          }
        });

        const result = await confluence.getSpaceByKey('SPACE');

        expect(result.key).toBe('SPACE');
        expect(mockAxios).toHaveBeenCalledWith(
          expect.objectContaining({
            params: expect.objectContaining({
              keys: 'SPACE',
              limit: 1
            })
          })
        );
      });

      it('should throw error if space not found', async () => {
        mockAxios.mockResolvedValueOnce({
          data: { results: [] }
        });

        await expect(confluence.getSpaceByKey('NOTFOUND'))
          .rejects.toThrow("Space with key 'NOTFOUND' not found");
      });
    });
  });

  describe('Pages', () => {
    describe('listPages', () => {
      it('should return formatted pages', async () => {
        mockAxios.mockResolvedValueOnce({
          data: {
            results: [
              {
                id: '1',
                title: 'Page 1',
                status: 'current',
                spaceId: '100',
                version: { number: 1, createdAt: '2024-01-01', authorId: 'user1' },
                parentId: '0',
                _links: { webui: '/wiki/spaces/SPACE/pages/1' }
              }
            ],
            _links: {}
          }
        });

        const result = await confluence.listPages({ spaceId: '100' });

        expect(result.pages).toHaveLength(1);
        expect(result.pages[0]).toMatchObject({
          id: '1',
          title: 'Page 1',
          status: 'current',
          spaceId: '100',
          version: 1
        });
      });

      it('should use space-specific endpoint when spaceId provided', async () => {
        mockAxios.mockResolvedValueOnce({
          data: { results: [], _links: {} }
        });

        await confluence.listPages({ spaceId: '100' });

        expect(mockAxios).toHaveBeenCalledWith(
          expect.objectContaining({
            url: expect.stringContaining('/spaces/100/pages')
          })
        );
      });
    });

    describe('getPage', () => {
      it('should return page with body content for full field set', async () => {
        mockAxios.mockResolvedValueOnce({
          data: {
            id: '1',
            title: 'Page',
            status: 'current',
            spaceId: '100',
            body: {
              storage: { value: '<p>Content</p>' }
            }
          }
        });

        const result = await confluence.getPage('1', { fieldSet: 'full' });

        expect(result.body).toBe('Content');
        expect(result.bodyRaw).toBe('<p>Content</p>');
      });

      it('should request specific body format', async () => {
        mockAxios.mockResolvedValueOnce({
          data: { id: '1', title: 'Page', status: 'current', spaceId: '100' }
        });

        await confluence.getPage('1', { bodyFormat: 'view' });

        expect(mockAxios).toHaveBeenCalledWith(
          expect.objectContaining({
            params: expect.objectContaining({
              'body-format': 'view'
            })
          })
        );
      });
    });

    describe('getPageByTitle', () => {
      it('should search for page by title in space', async () => {
        mockAxios.mockResolvedValueOnce({
          data: {
            results: [{ id: '1', title: 'My Page', status: 'current', spaceId: '100' }]
          }
        });

        const result = await confluence.getPageByTitle('100', 'My Page');

        expect(result.title).toBe('My Page');
      });

      it('should throw error if page not found', async () => {
        mockAxios.mockResolvedValueOnce({
          data: { results: [] }
        });

        await expect(confluence.getPageByTitle('100', 'NotFound'))
          .rejects.toThrow("Page 'NotFound' not found in space 100");
      });
    });
  });

  describe('Search', () => {
    describe('searchContent', () => {
      it('should search with CQL query', async () => {
        mockAxios.mockResolvedValueOnce({
          data: {
            results: [
              {
                content: { id: '1', type: 'page', title: 'Found', space: { key: 'SPACE', name: 'Space' } },
                excerpt: '<em>Found</em> content',
                lastModified: '2024-01-01'
              }
            ],
            totalSize: 1,
            _links: {}
          }
        });

        const result = await confluence.searchContent('search term');

        expect(result.results).toHaveLength(1);
        expect(result.results[0].title).toBe('Found');
        expect(result.results[0].excerpt).toBe('Found content'); // HTML stripped
      });

      it('should build CQL with space and type filters', async () => {
        mockAxios.mockResolvedValueOnce({
          data: { results: [], totalSize: 0, _links: {} }
        });

        await confluence.searchContent('term', { spaceKey: 'SPACE', type: 'page' });

        expect(mockAxios).toHaveBeenCalledWith(
          expect.objectContaining({
            params: expect.objectContaining({
              cql: expect.stringContaining('space = "SPACE"')
            })
          })
        );
      });
    });
  });

  describe('Labels', () => {
    describe('getPageLabels', () => {
      it('should return page labels', async () => {
        mockAxios.mockResolvedValueOnce({
          data: {
            results: [
              { id: '1', name: 'label1', prefix: 'global' },
              { id: '2', name: 'label2', prefix: 'my' }
            ]
          }
        });

        const result = await confluence.getPageLabels('123');

        expect(result.labels).toHaveLength(2);
        expect(result.labels[0]).toEqual({ id: '1', name: 'label1', prefix: 'global' });
      });
    });
  });

  describe('Watches', () => {
    describe('getWatchedContent', () => {
      it('should return watched content', async () => {
        mockAxios.mockResolvedValueOnce({
          data: {
            results: [
              { content: { id: '1', title: 'Watched Page', space: { key: 'SPACE' } } }
            ],
            totalSize: 1,
            start: 0,
            limit: 25
          }
        });

        const result = await confluence.getWatchedContent({ type: 'page' });

        expect(result.results).toHaveLength(1);
        expect(result.totalSize).toBe(1);
      });
    });

    describe('isWatchingContent', () => {
      it('should return watching status', async () => {
        mockAxios.mockResolvedValueOnce({
          data: { watching: true }
        });

        const result = await confluence.isWatchingContent('123');

        expect(result).toEqual({ contentId: '123', watching: true });
      });

      it('should return false for 404 response', async () => {
        mockAxios.mockRejectedValueOnce({ response: { status: 404 } });

        const result = await confluence.isWatchingContent('123');

        expect(result).toEqual({ contentId: '123', watching: false });
      });
    });

    describe('watchContent', () => {
      it('should start watching content', async () => {
        mockAxios.mockResolvedValueOnce({ data: {} });

        const result = await confluence.watchContent('123');

        expect(result).toEqual({
          contentId: '123',
          watching: true,
          message: 'Now watching this content'
        });
      });
    });

    describe('unwatchContent', () => {
      it('should stop watching content', async () => {
        mockAxios.mockResolvedValueOnce({ data: {} });

        const result = await confluence.unwatchContent('123');

        expect(result).toEqual({
          contentId: '123',
          watching: false,
          message: 'Stopped watching this content'
        });
      });
    });
  });

  describe('Formatting', () => {
    describe('extractTextFromStorage', () => {
      it('should strip HTML tags', () => {
        expect(confluence.extractTextFromStorage('<p>Hello <strong>World</strong></p>'))
          .toBe('Hello World');
      });

      it('should handle empty string', () => {
        expect(confluence.extractTextFromStorage('')).toBe('');
      });

      it('should truncate to 2000 characters', () => {
        const longHtml = '<p>' + 'x'.repeat(3000) + '</p>';
        expect(confluence.extractTextFromStorage(longHtml)).toHaveLength(2000);
      });
    });

    describe('stripHtml', () => {
      it('should strip HTML tags', () => {
        expect(confluence.stripHtml('<p>Test</p>')).toBe('Test');
      });

      it('should decode HTML entities', () => {
        expect(confluence.stripHtml('&amp; &lt; &gt; &quot;')).toBe('& < > "');
      });

      it('should normalize whitespace', () => {
        expect(confluence.stripHtml('<p>Hello</p>  <p>World</p>')).toBe('Hello World');
      });
    });

    describe('extractCursor', () => {
      it('should extract cursor from next link', () => {
        const nextLink = '/spaces?cursor=abc123&limit=25';
        expect(confluence.extractCursor(nextLink)).toBe('abc123');
      });

      it('should return null for no link', () => {
        expect(confluence.extractCursor(null)).toBeNull();
      });

      it('should handle URL-encoded cursor', () => {
        const nextLink = '/pages?cursor=a%3Db%26c';
        expect(confluence.extractCursor(nextLink)).toBe('a=b&c');
      });
    });

    describe('formatPage', () => {
      it('should format page with basic fields', () => {
        const page = {
          id: '1',
          title: 'Test',
          status: 'current',
          spaceId: '100'
        };

        const result = confluence.formatPage(page, CONFLUENCE_FIELD_SETS.minimal);

        expect(result).toEqual({
          id: '1',
          title: 'Test',
          status: 'current',
          spaceId: '100'
        });
      });

      it('should include version info when present', () => {
        const page = {
          id: '1',
          title: 'Test',
          status: 'current',
          spaceId: '100',
          version: { number: 5, createdAt: '2024-01-01', authorId: 'user1' }
        };

        const result = confluence.formatPage(page, CONFLUENCE_FIELD_SETS.standard);

        expect(result.version).toBe(5);
        expect(result.createdAt).toBe('2024-01-01');
        expect(result.authorId).toBe('user1');
      });

      it('should include labels when present', () => {
        const page = {
          id: '1',
          title: 'Test',
          status: 'current',
          spaceId: '100',
          labels: { results: [{ name: 'label1' }, { name: 'label2' }] }
        };

        const result = confluence.formatPage(page, CONFLUENCE_FIELD_SETS.extended);

        expect(result.labels).toEqual(['label1', 'label2']);
      });
    });
  });
});
