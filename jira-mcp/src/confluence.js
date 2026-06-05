/**
 * Confluence API Module
 * REST API v2 with configurable field sets
 */

const axios = require('axios');
const { getValidAccessToken, getCurrentUser } = require('./auth');
const fileStore = require('./file-store');

// Field sets for pages - control what data is returned
const CONFLUENCE_FIELD_SETS = {
  minimal: {
    // Just basic identifiers
    include: [],
    bodyFormat: null
  },
  standard: {
    // Include version info
    include: ['version'],
    bodyFormat: null
  },
  extended: {
    // Include labels and properties
    include: ['version', 'labels', 'properties'],
    bodyFormat: null
  },
  full: {
    // Include everything including body
    include: ['version', 'labels', 'properties', 'operations'],
    bodyFormat: 'storage' // storage, atlas_doc_format, or view
  }
};

class ConfluenceAPI {
  constructor() {
    this.initialized = false;
  }

  async getContext(options = {}) {
    const { forceRefresh = false } = options;

    if (forceRefresh) {
      this.initialized = false;
    }

    if (!this.initialized) {
      fileStore.init();
      this.initialized = true;
    }

    const token = await getValidAccessToken(getCurrentUser(), { forceRefresh });
    return {
      token,
      baseUrl: `https://api.atlassian.com/ex/confluence/${token.cloud_id}/wiki/api/v2`,
      v1BaseUrl: `https://api.atlassian.com/ex/confluence/${token.cloud_id}/wiki/rest/api`,
      accessToken: token.access_token,
      siteUrl: token.site_url
    };
  }

  getGrantedScopes(token) {
    return new Set((token?.scope || '').split(/\s+/).filter(Boolean));
  }

  assertScopes(token, requiredScopes = []) {
    if (!requiredScopes.length) return;

    const grantedScopes = this.getGrantedScopes(token);
    const missingScopes = requiredScopes.filter(scope => !grantedScopes.has(scope));

    if (missingScopes.length === 0) return;

    throw new Error(
      `Confluence access token is missing required OAuth scopes: ${missingScopes.join(', ')}. `
      + 'Update ATLASSIAN_SCOPES and run `npm run auth` to re-link your Atlassian account.'
    );
  }

  async init() {
    const { token } = await this.getContext();
    return {
      baseUrl: `https://api.atlassian.com/ex/confluence/${token.cloud_id}/wiki/api/v2`,
      accessToken: token.access_token,
      siteUrl: token.site_url
    };
  }

  async request(method, endpoint, data = null, params = null, requiredScopes = []) {
    const makeRequest = async (forceRefresh = false) => {
      const { token } = await this.getContext({ forceRefresh });
      this.assertScopes(token, requiredScopes);
      const config = {
        method,
        url: `https://api.atlassian.com/ex/confluence/${token.cloud_id}/wiki/api/v2${endpoint}`,
        headers: {
          Authorization: `Bearer ${token.access_token}`,
          'Content-Type': 'application/json'
        }
      };
      if (data) config.data = data;
      if (params) {
        // Filter out null/undefined params
        config.params = Object.fromEntries(
          Object.entries(params).filter(([_, v]) => v != null)
        );
      }

      const response = await axios(config);
      return response.data;
    };

    try {
      return await makeRequest(false);
    } catch (error) {
      if (error.response?.status !== 401) throw error;
      return await makeRequest(true);
    }
  }

  getFieldSetConfig(fieldSet = 'minimal') {
    return CONFLUENCE_FIELD_SETS[fieldSet] || CONFLUENCE_FIELD_SETS.minimal;
  }

  // === Spaces ===

  async listSpaces(options = {}) {
    const { limit = 25, cursor = null, type = null, status = 'current' } = options;

    const params = {
      limit: Math.min(limit, 250),
      status
    };
    if (cursor) params.cursor = cursor;
    if (type) params.type = type; // global, personal

    const data = await this.request('GET', '/spaces', null, params, ['read:space:confluence']);

    return {
      spaces: data.results.map(s => this.formatSpace(s)),
      nextCursor: this.extractCursor(data._links?.next),
      hasMore: !!data._links?.next
    };
  }

  async getSpace(spaceId) {
    const data = await this.request('GET', `/spaces/${spaceId}`, null, null, ['read:space:confluence']);
    return this.formatSpace(data, true);
  }

  async getSpaceByKey(spaceKey) {
    // Search for space by key
    const data = await this.request('GET', '/spaces', null, {
      keys: spaceKey,
      limit: 1
    }, ['read:space:confluence']);
    if (!data.results || data.results.length === 0) {
      throw new Error(`Space with key '${spaceKey}' not found`);
    }
    return this.formatSpace(data.results[0], true);
  }

  // === Pages ===

  async listPages(options = {}) {
    const {
      spaceId = null,
      limit = 25,
      cursor = null,
      status = 'current',
      sort = '-modified-date',
      fieldSet = 'minimal'
    } = options;

    const config = this.getFieldSetConfig(fieldSet);
    const params = {
      limit: Math.min(limit, 250),
      status,
      sort
    };
    if (cursor) params.cursor = cursor;
    if (config.bodyFormat) params['body-format'] = config.bodyFormat;

    let endpoint = '/pages';
    if (spaceId) {
      endpoint = `/spaces/${spaceId}/pages`;
    }

    const data = await this.request('GET', endpoint, null, params, ['read:page:confluence']);

    return {
      pages: data.results.map(p => this.formatPage(p, config)),
      nextCursor: this.extractCursor(data._links?.next),
      hasMore: !!data._links?.next
    };
  }

  async getPage(pageId, options = {}) {
    const { fieldSet = 'standard', bodyFormat = null } = options;
    const config = this.getFieldSetConfig(fieldSet);

    const params = {};
    // Use explicit bodyFormat or from fieldSet
    const format = bodyFormat || config.bodyFormat;
    if (format) params['body-format'] = format;

    const data = await this.request('GET', `/pages/${pageId}`, null, params, ['read:page:confluence']);
    return this.formatPage(data, config, true);
  }

  async getPageByTitle(spaceId, title, options = {}) {
    const { fieldSet = 'standard' } = options;
    const config = this.getFieldSetConfig(fieldSet);

    const params = {
      title,
      limit: 1
    };
    if (config.bodyFormat) params['body-format'] = config.bodyFormat;

    const data = await this.request('GET', `/spaces/${spaceId}/pages`, null, params, ['read:page:confluence']);
    if (!data.results || data.results.length === 0) {
      throw new Error(`Page '${title}' not found in space ${spaceId}`);
    }
    return this.formatPage(data.results[0], config, true);
  }

  // === Search ===

  async searchContent(query, options = {}) {
    const {
      limit = 25,
      cursor = null,
      spaceKey = null,
      type = null // page, blogpost, comment, attachment
    } = options;

    // Build CQL query
    let cql = `text ~ "${query.replace(/"/g, '\\"')}"`;
    if (spaceKey) cql += ` AND space = "${spaceKey}"`;
    if (type) cql += ` AND type = "${type}"`;

    const params = {
      cql,
      limit: Math.min(limit, 100)
    };
    if (cursor) params.cursor = cursor;

    // Use v1 search API (v2 doesn't have search endpoint yet)
    const { token, v1BaseUrl, accessToken } = await this.getContext();
    this.assertScopes(token, ['search:confluence']);

    const response = await axios({
      method: 'GET',
      url: `${v1BaseUrl}/content/search`,
      headers: {
        Authorization: `Bearer ${accessToken}`,
        'Content-Type': 'application/json'
      },
      params
    });

    const data = response.data;
    return {
      results: data.results.map(r => this.formatSearchResult(r)),
      totalSize: data.totalSize,
      nextCursor: this.extractCursor(data._links?.next),
      hasMore: !!data._links?.next
    };
  }

  // === Labels ===

  async getPageLabels(pageId) {
    const data = await this.request('GET', `/pages/${pageId}/labels`, null, null, ['read:label:confluence']);
    return {
      labels: data.results.map(l => ({
        id: l.id,
        name: l.name,
        prefix: l.prefix
      }))
    };
  }

  // === Watches (V1 API) ===

  async getWatchedContent(options = {}) {
    const {
      limit = 25,
      start = 0,
      type = 'page' // page, blogpost, or null for all
    } = options;

    // Use CQL with watcher = currentUser()
    let cql = 'watcher = currentUser()';
    if (type) cql += ` AND type = "${type}"`;

    const { token, v1BaseUrl, accessToken } = await this.getContext();
    this.assertScopes(token, ['search:confluence', 'read:watcher:confluence']);

    const response = await axios({
      method: 'GET',
      url: `${v1BaseUrl}/content/search`,
      headers: {
        Authorization: `Bearer ${accessToken}`,
        'Content-Type': 'application/json'
      },
      params: {
        cql,
        limit: Math.min(limit, 100),
        start
      }
    });

    const data = response.data;
    return {
      results: data.results.map(r => this.formatSearchResult(r)),
      totalSize: data.totalSize,
      start: data.start,
      limit: data.limit,
      hasMore: (data.start + data.results.length) < data.totalSize
    };
  }

  async isWatchingContent(contentId) {
    const { token, v1BaseUrl, accessToken } = await this.getContext();
    this.assertScopes(token, ['read:watcher:confluence']);

    try {
      const response = await axios({
        method: 'GET',
        url: `${v1BaseUrl}/user/watch/content/${contentId}`,
        headers: {
          Authorization: `Bearer ${accessToken}`,
          'Content-Type': 'application/json'
        }
      });
      return { contentId, watching: response.data.watching || false };
    } catch (error) {
      if (error.response?.status === 404) {
        return { contentId, watching: false };
      }
      throw error;
    }
  }

  async watchContent(contentId) {
    const { token, v1BaseUrl, accessToken } = await this.getContext();
    this.assertScopes(token, ['write:watcher:confluence']);

    await axios({
      method: 'POST',
      url: `${v1BaseUrl}/user/watch/content/${contentId}`,
      headers: {
        Authorization: `Bearer ${accessToken}`,
        'Content-Type': 'application/json',
        'X-Atlassian-Token': 'no-check'
      }
    });
    return { contentId, watching: true, message: 'Now watching this content' };
  }

  async unwatchContent(contentId) {
    const { token, v1BaseUrl, accessToken } = await this.getContext();
    this.assertScopes(token, ['write:watcher:confluence']);

    await axios({
      method: 'DELETE',
      url: `${v1BaseUrl}/user/watch/content/${contentId}`,
      headers: {
        Authorization: `Bearer ${accessToken}`,
        'Content-Type': 'application/json',
        'X-Atlassian-Token': 'no-check'
      }
    });
    return { contentId, watching: false, message: 'Stopped watching this content' };
  }

  async getWatchedSpaces(options = {}) {
    const { limit = 25, start = 0 } = options;

    // Use CQL with watcher = currentUser() for spaces
    const cql = 'watcher = currentUser() AND type = space';

    const { token, v1BaseUrl, accessToken } = await this.getContext();
    this.assertScopes(token, ['search:confluence', 'read:watcher:confluence']);

    try {
      const response = await axios({
        method: 'GET',
        url: `${v1BaseUrl}/content/search`,
        headers: {
          Authorization: `Bearer ${accessToken}`,
          'Content-Type': 'application/json'
        },
        params: {
          cql,
          limit: Math.min(limit, 100),
          start
        }
      });

      const data = response.data;
      return {
        results: data.results.map(r => ({
          key: r.space?.key,
          name: r.space?.name,
          type: r.space?.type
        })),
        totalSize: data.totalSize,
        hasMore: (data.start + data.results.length) < data.totalSize
      };
    } catch (error) {
      // Fallback: space watching may not be searchable via CQL
      return { results: [], totalSize: 0, hasMore: false, note: 'Space watch search not available' };
    }
  }

  // === Formatting ===

  formatSpace(space, includeDetails = false) {
    const result = {
      id: space.id,
      key: space.key,
      name: space.name,
      type: space.type,
      status: space.status
    };

    if (includeDetails) {
      if (space.description?.plain?.value) {
        result.description = space.description.plain.value;
      }
      if (space.homepageId) result.homepageId = space.homepageId;
      if (space.createdAt) result.createdAt = space.createdAt;
    }

    return result;
  }

  formatPage(page, config, includeBody = false) {
    const result = {
      id: page.id,
      title: page.title,
      status: page.status,
      spaceId: page.spaceId
    };

    // Version info (standard+)
    if (page.version) {
      result.version = page.version.number;
      result.createdAt = page.version.createdAt;
      if (page.version.authorId) result.authorId = page.version.authorId;
    }

    // Parent page
    if (page.parentId) result.parentId = page.parentId;
    if (page.parentType) result.parentType = page.parentType;

    // Labels (extended+)
    if (page.labels?.results) {
      result.labels = page.labels.results.map(l => l.name);
    }

    // Body content (full or explicit request)
    if (includeBody && page.body) {
      if (page.body.storage?.value) {
        result.body = this.extractTextFromStorage(page.body.storage.value);
        result.bodyRaw = page.body.storage.value;
      } else if (page.body.atlas_doc_format?.value) {
        result.body = this.extractTextFromAdf(JSON.parse(page.body.atlas_doc_format.value));
      } else if (page.body.view?.value) {
        result.body = this.stripHtml(page.body.view.value);
      }
    }

    // Web URL
    if (page._links?.webui) {
      result.webUrl = page._links.webui;
    }

    return result;
  }

  formatSearchResult(result) {
    return {
      id: result.content?.id || result.id,
      type: result.content?.type || result.type,
      title: result.content?.title || result.title,
      spaceKey: result.content?.space?.key || result.space?.key,
      spaceName: result.content?.space?.name || result.space?.name,
      excerpt: result.excerpt ? this.stripHtml(result.excerpt) : null,
      lastModified: result.lastModified,
      url: result.url || result._links?.webui
    };
  }

  extractTextFromStorage(storageXml) {
    if (!storageXml) return '';
    // Simple HTML/XML tag stripping
    return this.stripHtml(storageXml).slice(0, 2000);
  }

  extractTextFromAdf(adf) {
    if (!adf) return '';
    if (typeof adf === 'string') return adf;

    const extract = (node) => {
      if (!node) return '';
      if (node.type === 'text') return node.text || '';
      if (node.content) return node.content.map(extract).join('');
      return '';
    };

    return extract(adf).slice(0, 2000);
  }

  stripHtml(html) {
    if (!html) return '';
    return html
      .replace(/<[^>]*>/g, ' ')
      .replace(/&nbsp;/g, ' ')
      .replace(/&amp;/g, '&')
      .replace(/&lt;/g, '<')
      .replace(/&gt;/g, '>')
      .replace(/&quot;/g, '"')
      .replace(/\s+/g, ' ')
      .trim();
  }

  extractCursor(nextLink) {
    if (!nextLink) return null;
    const match = nextLink.match(/cursor=([^&]+)/);
    return match ? decodeURIComponent(match[1]) : null;
  }
}

module.exports = { ConfluenceAPI, CONFLUENCE_FIELD_SETS };
