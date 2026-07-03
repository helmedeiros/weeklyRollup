/**
 * Google Drive API Wrapper
 * Provides methods for file and folder operations
 */

import { google } from 'googleapis';

// MIME types for Google Workspace documents
const GOOGLE_DOC_TYPES = {
  'application/vnd.google-apps.document': {
    name: 'Google Doc',
    exportMimeType: 'text/plain',
    extension: 'txt',
  },
  'application/vnd.google-apps.spreadsheet': {
    name: 'Google Sheet',
    exportMimeType: 'text/csv',
    extension: 'csv',
  },
  'application/vnd.google-apps.presentation': {
    name: 'Google Slides',
    exportMimeType: 'text/plain',
    extension: 'txt',
  },
  'application/vnd.google-apps.drawing': {
    name: 'Google Drawing',
    exportMimeType: 'image/png',
    extension: 'png',
  },
};

const DOWNLOAD_EXTENSION_BY_MIME_TYPE = {
  'application/pdf': 'pdf',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'docx',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'xlsx',
  'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'pptx',
  'image/png': 'png',
  'text/csv': 'csv',
  'text/html': 'html',
  'text/plain': 'txt',
};

function appendDownloadExtension(fileName, mimeType, fallbackExtension) {
  const extension = DOWNLOAD_EXTENSION_BY_MIME_TYPE[mimeType] || fallbackExtension;
  if (!extension || fileName.endsWith(`.${extension}`)) {
    return fileName;
  }
  return `${fileName}.${extension}`;
}

export class DriveAPI {
  constructor(authClient) {
    this.authClient = authClient;
    this.drive = google.drive({ version: 'v3', auth: authClient });
  }

  // ===== FILE LISTING =====

  /**
   * List files and folders
   * @param {Object} options - Query options
   * @param {string} options.query - Drive query string (e.g., "name contains 'report'")
   * @param {string} options.folderId - Folder ID to list contents of
   * @param {number} options.pageSize - Number of files to return (default: 100)
   * @param {string} options.pageToken - Token for pagination
   * @param {string} options.orderBy - Order by field (e.g., "modifiedTime desc")
   * @param {boolean} options.includeTrashed - Include trashed files (default: false)
   */
  async listFiles(options = {}) {
    const {
      query,
      folderId,
      pageSize = 100,
      pageToken,
      orderBy = 'modifiedTime desc',
      includeTrashed = false,
    } = options;

    // Build query
    let q = [];
    if (query) q.push(query);
    if (folderId) q.push(`'${folderId}' in parents`);
    if (!includeTrashed) q.push('trashed = false');

    const params = {
      pageSize,
      orderBy,
      fields: 'nextPageToken, files(id, name, mimeType, size, createdTime, modifiedTime, parents, webViewLink, iconLink, owners, shared, driveId)',
      supportsAllDrives: true,
      includeItemsFromAllDrives: true,
    };

    if (q.length > 0) params.q = q.join(' and ');
    if (pageToken) params.pageToken = pageToken;

    const response = await this.drive.files.list(params);
    return {
      files: response.data.files || [],
      nextPageToken: response.data.nextPageToken,
    };
  }

  /**
   * Search for files using Drive query syntax
   * @param {string} searchQuery - Search query (name, content, type, etc.)
   * @param {Object} options - Additional options
   */
  async searchFiles(searchQuery, options = {}) {
    const {
      pageSize = 50,
      pageToken,
      orderBy = 'modifiedTime desc',
      fileType,
      includeTrashed = false,
    } = options;

    // Build query
    let q = [];

    // Handle full-text search
    if (searchQuery) {
      q.push(`fullText contains '${searchQuery.replace(/'/g, "\\'")}'`);
    }

    // Filter by file type
    if (fileType) {
      const mimeTypeMap = {
        'document': 'application/vnd.google-apps.document',
        'spreadsheet': 'application/vnd.google-apps.spreadsheet',
        'presentation': 'application/vnd.google-apps.presentation',
        'folder': 'application/vnd.google-apps.folder',
        'pdf': 'application/pdf',
        'image': 'image/',
        'video': 'video/',
        'audio': 'audio/',
      };

      if (mimeTypeMap[fileType]) {
        if (fileType === 'image' || fileType === 'video' || fileType === 'audio') {
          q.push(`mimeType contains '${mimeTypeMap[fileType]}'`);
        } else {
          q.push(`mimeType = '${mimeTypeMap[fileType]}'`);
        }
      }
    }

    if (!includeTrashed) q.push('trashed = false');

    const params = {
      pageSize,
      orderBy,
      fields: 'nextPageToken, files(id, name, mimeType, size, createdTime, modifiedTime, parents, webViewLink, iconLink, owners, shared, driveId)',
      supportsAllDrives: true,
      includeItemsFromAllDrives: true,
    };

    if (q.length > 0) params.q = q.join(' and ');
    if (pageToken) params.pageToken = pageToken;

    const response = await this.drive.files.list(params);
    return {
      files: response.data.files || [],
      nextPageToken: response.data.nextPageToken,
    };
  }

  // ===== FILE OPERATIONS =====

  /**
   * Get file metadata by ID
   */
  async getFile(fileId) {
    const response = await this.drive.files.get({
      fileId,
      fields: 'id, name, mimeType, size, createdTime, modifiedTime, parents, webViewLink, webContentLink, iconLink, owners, shared, description, starred, trashed, permissions, driveId',
      supportsAllDrives: true,
    });
    return response.data;
  }

  /**
   * Get file content
   * For Google Docs/Sheets/Slides, exports to text/csv format
   * For other files, downloads the content
   */
  async getFileContent(fileId, options = {}) {
    // First get file metadata to determine type
    const file = await this.getFile(fileId);
    const mimeType = file.mimeType;

    // Check if it's a Google Workspace document
    const googleDocType = GOOGLE_DOC_TYPES[mimeType];

    if (googleDocType) {
      // Export Google Workspace documents
      const exportMimeType = options.exportMimeType || googleDocType.exportMimeType;
      const response = await this.drive.files.export({
        fileId,
        mimeType: exportMimeType,
      }, { responseType: 'text' });

      return {
        content: response.data,
        mimeType: exportMimeType,
        fileName: file.name,
        originalMimeType: mimeType,
        isExported: true,
      };
    } else {
      // Download regular files
      const response = await this.drive.files.get({
        fileId,
        alt: 'media',
        supportsAllDrives: true,
      }, { responseType: 'text' });

      return {
        content: response.data,
        mimeType: file.mimeType,
        fileName: file.name,
        isExported: false,
      };
    }
  }

  /**
   * Download a file without lossy text decoding.
   * For Google Workspace files, exports to the requested/default MIME type.
   * For regular files, downloads the original bytes.
   */
  async downloadFile(fileId, options = {}) {
    const file = await this.getFile(fileId);
    const mimeType = file.mimeType;
    const googleDocType = GOOGLE_DOC_TYPES[mimeType];

    let response;
    let downloadMimeType;
    let isExported = false;
    let fileName = file.name;

    if (googleDocType) {
      downloadMimeType = options.exportMimeType || googleDocType.exportMimeType;
      isExported = true;
      fileName = appendDownloadExtension(fileName, downloadMimeType, googleDocType.extension);

      response = await this.drive.files.export({
        fileId,
        mimeType: downloadMimeType,
      }, { responseType: 'arraybuffer' });
    } else {
      downloadMimeType = mimeType;
      response = await this.drive.files.get({
        fileId,
        alt: 'media',
        supportsAllDrives: true,
      }, { responseType: 'arraybuffer' });
    }

    const buffer = Buffer.from(response.data);

    return {
      content: buffer,
      contentBase64: buffer.toString('base64'),
      sizeBytes: buffer.length,
      mimeType: downloadMimeType,
      fileName,
      originalMimeType: mimeType,
      isExported,
    };
  }

  /**
   * Update file metadata
   */
  async updateFile(fileId, metadata) {
    const response = await this.drive.files.update({
      fileId,
      requestBody: metadata,
      fields: 'id, name, mimeType, size, createdTime, modifiedTime, parents, webViewLink, description, starred',
      supportsAllDrives: true,
    });
    return response.data;
  }

  /**
   * Update file content
   * @param {string} fileId - File ID
   * @param {string|Buffer} content - New content
   * @param {string} mimeType - Content MIME type
   */
  async updateFileContent(fileId, content, mimeType = 'text/plain') {
    const response = await this.drive.files.update({
      fileId,
      media: {
        mimeType,
        body: content,
      },
      fields: 'id, name, mimeType, size, modifiedTime',
      supportsAllDrives: true,
    });
    return response.data;
  }

  /**
   * Delete (trash) a file
   */
  async deleteFile(fileId, permanent = false) {
    if (permanent) {
      await this.drive.files.delete({ fileId, supportsAllDrives: true });
      return { success: true, fileId, action: 'permanently_deleted' };
    } else {
      await this.drive.files.update({
        fileId,
        requestBody: { trashed: true },
        supportsAllDrives: true,
      });
      return { success: true, fileId, action: 'trashed' };
    }
  }

  /**
   * Restore a file from trash
   */
  async restoreFile(fileId) {
    const response = await this.drive.files.update({
      fileId,
      requestBody: { trashed: false },
      fields: 'id, name, mimeType, modifiedTime',
      supportsAllDrives: true,
    });
    return response.data;
  }

  // ===== FOLDER OPERATIONS =====

  /**
   * Create a new folder
   */
  async createFolder(name, parentFolderId = null) {
    const metadata = {
      name,
      mimeType: 'application/vnd.google-apps.folder',
    };

    if (parentFolderId) {
      metadata.parents = [parentFolderId];
    }

    const response = await this.drive.files.create({
      requestBody: metadata,
      fields: 'id, name, mimeType, createdTime, webViewLink',
      supportsAllDrives: true,
    });
    return response.data;
  }

  // ===== FILE UPLOAD =====

  /**
   * Upload a new file
   * @param {string} name - File name
   * @param {string|Buffer} content - File content
   * @param {string} mimeType - Content MIME type
   * @param {string} parentFolderId - Optional parent folder ID
   */
  async uploadFile(name, content, mimeType = 'text/plain', parentFolderId = null) {
    const metadata = { name };
    if (parentFolderId) {
      metadata.parents = [parentFolderId];
    }

    const response = await this.drive.files.create({
      requestBody: metadata,
      media: {
        mimeType,
        body: content,
      },
      fields: 'id, name, mimeType, size, createdTime, webViewLink',
      supportsAllDrives: true,
    });
    return response.data;
  }

  /**
   * Upload a file from local filesystem (supports binary files like images, PDFs)
   * @param {string} localPath - Absolute path to the local file
   * @param {string} name - Optional name for the file in Drive (defaults to original filename)
   * @param {string} parentFolderId - Optional parent folder ID
   */
  async uploadLocalFile(localPath, name = null, parentFolderId = null) {
    const { createReadStream, existsSync, statSync } = await import('fs');
    const { basename, extname } = await import('path');

    // Verify file exists
    if (!existsSync(localPath)) {
      throw new Error(`File not found: ${localPath}`);
    }

    // Get file stats
    const stats = statSync(localPath);
    if (!stats.isFile()) {
      throw new Error(`Not a file: ${localPath}`);
    }

    // Determine filename and MIME type
    const fileName = name || basename(localPath);
    const mimeType = this.getMimeType(extname(localPath).toLowerCase());

    // Create read stream for the file
    const fileStream = createReadStream(localPath);

    const metadata = { name: fileName };
    if (parentFolderId) {
      metadata.parents = [parentFolderId];
    }

    const response = await this.drive.files.create({
      requestBody: metadata,
      media: {
        mimeType,
        body: fileStream,
      },
      fields: 'id, name, mimeType, size, createdTime, webViewLink',
      supportsAllDrives: true,
    });

    return {
      ...response.data,
      localPath,
      uploadedSize: stats.size,
    };
  }

  /**
   * Upload a file from base64-encoded content
   * @param {string} base64Content - Base64-encoded file content
   * @param {string} name - File name (used for MIME type detection and Drive filename)
   * @param {string} mimeType - Optional explicit MIME type (auto-detected from name if not provided)
   * @param {string} parentFolderId - Optional parent folder ID
   */
  async uploadFromBase64(base64Content, name, mimeType = null, parentFolderId = null) {
    const { extname } = await import('path');

    // Decode base64 to Buffer
    const buffer = Buffer.from(base64Content, 'base64');

    // Auto-detect MIME type from filename if not provided
    const resolvedMimeType = mimeType || this.getMimeType(extname(name).toLowerCase());

    const metadata = { name };
    if (parentFolderId) {
      metadata.parents = [parentFolderId];
    }

    const { Readable } = await import('stream');
    const stream = Readable.from(buffer);

    const response = await this.drive.files.create({
      requestBody: metadata,
      media: {
        mimeType: resolvedMimeType,
        body: stream,
      },
      fields: 'id, name, mimeType, size, createdTime, webViewLink',
      supportsAllDrives: true,
    });

    return {
      ...response.data,
      uploadedSize: buffer.length,
    };
  }

  /**
   * Get MIME type based on file extension
   * @param {string} ext - File extension (e.g., '.jpg', '.pdf')
   */
  getMimeType(ext) {
    const mimeTypes = {
      // Images
      '.jpg': 'image/jpeg',
      '.jpeg': 'image/jpeg',
      '.png': 'image/png',
      '.gif': 'image/gif',
      '.bmp': 'image/bmp',
      '.webp': 'image/webp',
      '.svg': 'image/svg+xml',
      '.ico': 'image/x-icon',
      '.tiff': 'image/tiff',
      '.tif': 'image/tiff',
      '.heic': 'image/heic',
      '.heif': 'image/heif',

      // Documents
      '.pdf': 'application/pdf',
      '.doc': 'application/msword',
      '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      '.xls': 'application/vnd.ms-excel',
      '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      '.ppt': 'application/vnd.ms-powerpoint',
      '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
      '.odt': 'application/vnd.oasis.opendocument.text',
      '.ods': 'application/vnd.oasis.opendocument.spreadsheet',
      '.odp': 'application/vnd.oasis.opendocument.presentation',
      '.rtf': 'application/rtf',

      // Text
      '.txt': 'text/plain',
      '.csv': 'text/csv',
      '.html': 'text/html',
      '.htm': 'text/html',
      '.css': 'text/css',
      '.js': 'application/javascript',
      '.json': 'application/json',
      '.xml': 'application/xml',
      '.md': 'text/markdown',
      '.yaml': 'text/yaml',
      '.yml': 'text/yaml',

      // Archives
      '.zip': 'application/zip',
      '.gz': 'application/gzip',
      '.tar': 'application/x-tar',
      '.rar': 'application/vnd.rar',
      '.7z': 'application/x-7z-compressed',

      // Audio
      '.mp3': 'audio/mpeg',
      '.wav': 'audio/wav',
      '.ogg': 'audio/ogg',
      '.m4a': 'audio/mp4',
      '.flac': 'audio/flac',
      '.aac': 'audio/aac',

      // Video
      '.mp4': 'video/mp4',
      '.webm': 'video/webm',
      '.avi': 'video/x-msvideo',
      '.mov': 'video/quicktime',
      '.mkv': 'video/x-matroska',
      '.wmv': 'video/x-ms-wmv',

      // Other
      '.exe': 'application/x-msdownload',
      '.dmg': 'application/x-apple-diskimage',
      '.iso': 'application/x-iso9660-image',
    };

    return mimeTypes[ext] || 'application/octet-stream';
  }

  /**
   * Create a new Google Doc
   * @param {string} name - Document name
   * @param {string} content - Optional initial content (plain text)
   * @param {string} parentFolderId - Optional parent folder ID
   */
  async createGoogleDoc(name, content = '', parentFolderId = null) {
    const metadata = {
      name,
      mimeType: 'application/vnd.google-apps.document',
    };

    if (parentFolderId) {
      metadata.parents = [parentFolderId];
    }

    // Create empty Google Doc first
    const response = await this.drive.files.create({
      requestBody: metadata,
      fields: 'id, name, mimeType, createdTime, webViewLink',
      supportsAllDrives: true,
    });

    return response.data;
  }

  /**
   * Copy a file
   */
  async copyFile(fileId, newName, parentFolderId = null) {
    const metadata = {};
    if (newName) metadata.name = newName;
    if (parentFolderId) metadata.parents = [parentFolderId];

    const response = await this.drive.files.copy({
      fileId,
      requestBody: metadata,
      fields: 'id, name, mimeType, size, createdTime, webViewLink',
      supportsAllDrives: true,
    });
    return response.data;
  }

  /**
   * Move a file to a different folder
   */
  async moveFile(fileId, newParentFolderId) {
    // First get current parents
    const file = await this.getFile(fileId);
    const previousParents = file.parents?.join(',') || '';

    const response = await this.drive.files.update({
      fileId,
      addParents: newParentFolderId,
      removeParents: previousParents,
      fields: 'id, name, parents',
      supportsAllDrives: true,
    });
    return response.data;
  }

  // ===== SHARING =====

  /**
   * Share a file with users, groups, domains, or anyone (public)
   * @param {string} fileId - File ID
   * @param {string} type - Permission type: 'user', 'group', 'domain', 'anyone'
   * @param {string} role - Permission role: 'reader', 'writer', 'commenter'
   * @param {object} options - Additional options
   * @param {string} options.email - Email address (required for 'user' and 'group' types)
   * @param {string} options.domain - Domain (required for 'domain' type)
   * @param {boolean} options.sendNotification - Send email notification (default: true)
   * @param {boolean} options.allowFileDiscovery - Allow file to appear in search results for 'anyone' or 'domain' (default: false)
   */
  async shareFile(fileId, type = 'user', role = 'reader', options = {}) {
    const { email, domain, sendNotification = true, allowFileDiscovery = false } = options;

    // Build permission request body based on type
    const requestBody = { type, role };

    switch (type) {
      case 'user':
      case 'group':
        if (!email) {
          throw new Error(`Email address is required for type '${type}'`);
        }
        requestBody.emailAddress = email;
        break;
      case 'domain':
        if (!domain) {
          throw new Error("Domain is required for type 'domain'");
        }
        requestBody.domain = domain;
        requestBody.allowFileDiscovery = allowFileDiscovery;
        break;
      case 'anyone':
        requestBody.allowFileDiscovery = allowFileDiscovery;
        break;
      default:
        throw new Error(`Invalid permission type: ${type}. Must be 'user', 'group', 'domain', or 'anyone'`);
    }

    const response = await this.drive.permissions.create({
      fileId,
      sendNotificationEmail: type === 'user' || type === 'group' ? sendNotification : false,
      requestBody,
      supportsAllDrives: true,
    });

    return response.data;
  }

  /**
   * Get file permissions
   */
  async getPermissions(fileId) {
    const response = await this.drive.permissions.list({
      fileId,
      fields: 'permissions(id, type, role, emailAddress, displayName)',
      supportsAllDrives: true,
    });
    return response.data.permissions || [];
  }

  /**
   * Remove a permission
   */
  async removePermission(fileId, permissionId) {
    await this.drive.permissions.delete({
      fileId,
      permissionId,
      supportsAllDrives: true,
    });
    return { success: true };
  }

  // ===== COMMENTS =====

  /**
   * List comments on a file
   * @param {string} fileId - File ID
   * @param {Object} options - Options
   * @param {number} options.pageSize - Number of comments to return (default: 100)
   * @param {string} options.pageToken - Token for pagination
   * @param {boolean} options.includeDeleted - Include deleted comments (default: false)
   */
  async listComments(fileId, options = {}) {
    const { pageSize = 100, pageToken, includeDeleted = false } = options;

    const response = await this.drive.comments.list({
      fileId,
      pageSize,
      pageToken,
      includeDeleted,
      fields: 'nextPageToken, comments(id, content, author, createdTime, modifiedTime, resolved, replies, quotedFileContent, anchor)',
    });

    return {
      comments: response.data.comments || [],
      nextPageToken: response.data.nextPageToken,
    };
  }

  /**
   * Get a specific comment with its replies
   * @param {string} fileId - File ID
   * @param {string} commentId - Comment ID
   */
  async getComment(fileId, commentId) {
    const response = await this.drive.comments.get({
      fileId,
      commentId,
      includeDeleted: false,
      fields: 'id, content, author, createdTime, modifiedTime, resolved, replies, quotedFileContent, anchor',
    });
    return response.data;
  }

  /**
   * Create a comment on a file
   * @param {string} fileId - File ID
   * @param {string} content - Comment text
   * @param {Object} options - Options
   * @param {string} options.quotedFileContent - Text in document to anchor comment to
   */
  async createComment(fileId, content, options = {}) {
    const requestBody = { content };

    // For anchoring to specific text in Google Docs
    if (options.quotedFileContent) {
      requestBody.quotedFileContent = {
        value: options.quotedFileContent,
      };
    }

    const response = await this.drive.comments.create({
      fileId,
      requestBody,
      fields: 'id, content, author, createdTime, modifiedTime, resolved, quotedFileContent, anchor',
    });
    return response.data;
  }

  /**
   * Update a comment
   * @param {string} fileId - File ID
   * @param {string} commentId - Comment ID
   * @param {string} content - New comment text
   */
  async updateComment(fileId, commentId, content) {
    const response = await this.drive.comments.update({
      fileId,
      commentId,
      requestBody: { content },
      fields: 'id, content, author, createdTime, modifiedTime, resolved',
    });
    return response.data;
  }

  /**
   * Resolve or reopen a comment
   * @param {string} fileId - File ID
   * @param {string} commentId - Comment ID
   * @param {boolean} resolved - true to resolve, false to reopen
   */
  async resolveComment(fileId, commentId, resolved = true) {
    // To resolve/unresolve, we need to create a reply with action
    // But the simpler approach is updating with a reply that has action=resolve
    // Actually, the Drive API doesn't have a direct resolve method.
    // We need to create a reply with action='resolve' or 'reopen'
    const response = await this.drive.replies.create({
      fileId,
      commentId,
      requestBody: {
        action: resolved ? 'resolve' : 'reopen',
        content: resolved ? 'Resolved' : 'Reopened',
      },
      fields: 'id, content, author, createdTime, action',
    });
    return {
      success: true,
      action: resolved ? 'resolved' : 'reopened',
      reply: response.data,
    };
  }

  /**
   * Delete a comment
   * @param {string} fileId - File ID
   * @param {string} commentId - Comment ID
   */
  async deleteComment(fileId, commentId) {
    await this.drive.comments.delete({
      fileId,
      commentId,
    });
    return { success: true, commentId, action: 'deleted' };
  }

  /**
   * Reply to a comment
   * @param {string} fileId - File ID
   * @param {string} commentId - Comment ID
   * @param {string} content - Reply text
   */
  async replyToComment(fileId, commentId, content) {
    const response = await this.drive.replies.create({
      fileId,
      commentId,
      requestBody: { content },
      fields: 'id, content, author, createdTime, modifiedTime',
    });
    return response.data;
  }

  /**
   * Delete a reply
   * @param {string} fileId - File ID
   * @param {string} commentId - Comment ID
   * @param {string} replyId - Reply ID
   */
  async deleteReply(fileId, commentId, replyId) {
    await this.drive.replies.delete({
      fileId,
      commentId,
      replyId,
    });
    return { success: true, replyId, action: 'deleted' };
  }

  // ===== REVISIONS (VERSION HISTORY) =====

  /**
   * List all revisions of a file
   * @param {string} fileId - File ID
   * @param {Object} options - Options
   * @param {number} options.pageSize - Number of revisions to return (default: 100)
   * @param {string} options.pageToken - Token for pagination
   */
  async listRevisions(fileId, options = {}) {
    const { pageSize = 100, pageToken } = options;

    const response = await this.drive.revisions.list({
      fileId,
      pageSize,
      pageToken,
      fields: 'nextPageToken, revisions(id, mimeType, modifiedTime, keepForever, published, publishAuto, publishedOutsideDomain, size, lastModifyingUser, originalFilename, exportLinks)',
    });

    return {
      revisions: response.data.revisions || [],
      nextPageToken: response.data.nextPageToken,
    };
  }

  /**
   * Get a specific revision
   * @param {string} fileId - File ID
   * @param {string} revisionId - Revision ID
   */
  async getRevision(fileId, revisionId) {
    const response = await this.drive.revisions.get({
      fileId,
      revisionId,
      fields: 'id, mimeType, modifiedTime, keepForever, published, publishAuto, publishedOutsideDomain, size, lastModifyingUser, originalFilename, exportLinks',
    });
    return response.data;
  }

  /**
   * Update revision properties
   * @param {string} fileId - File ID
   * @param {string} revisionId - Revision ID
   * @param {Object} updates - Properties to update
   * @param {boolean} updates.keepForever - Keep this revision permanently (prevents auto-deletion)
   * @param {boolean} updates.publishAuto - Automatically publish new revisions
   * @param {boolean} updates.published - Publish this revision for web viewing
   * @param {boolean} updates.publishedOutsideDomain - Allow viewing outside domain
   */
  async updateRevision(fileId, revisionId, updates) {
    const requestBody = {};
    if (updates.keepForever !== undefined) requestBody.keepForever = updates.keepForever;
    if (updates.publishAuto !== undefined) requestBody.publishAuto = updates.publishAuto;
    if (updates.published !== undefined) requestBody.published = updates.published;
    if (updates.publishedOutsideDomain !== undefined) requestBody.publishedOutsideDomain = updates.publishedOutsideDomain;

    const response = await this.drive.revisions.update({
      fileId,
      revisionId,
      requestBody,
      fields: 'id, mimeType, modifiedTime, keepForever, published, publishAuto, publishedOutsideDomain, size, lastModifyingUser',
    });
    return response.data;
  }

  /**
   * Delete a revision
   * Note: Cannot delete the last remaining revision or revisions marked as keepForever
   * @param {string} fileId - File ID
   * @param {string} revisionId - Revision ID
   */
  async deleteRevision(fileId, revisionId) {
    await this.drive.revisions.delete({
      fileId,
      revisionId,
    });
    return { success: true, revisionId, action: 'deleted' };
  }

  /**
   * Download content of a specific revision
   * @param {string} fileId - File ID
   * @param {string} revisionId - Revision ID
   * @param {string} exportMimeType - MIME type for export (for Google Workspace files)
   */
  async downloadRevision(fileId, revisionId, exportMimeType = null) {
    // Get revision metadata first
    const revision = await this.getRevision(fileId, revisionId);

    // For Google Workspace files, use export
    if (revision.exportLinks && exportMimeType && revision.exportLinks[exportMimeType]) {
      const response = await this.authClient.request({
        url: revision.exportLinks[exportMimeType],
        responseType: 'arraybuffer',
      });
      const buffer = Buffer.from(response.data);

      return {
        content: buffer,
        contentBase64: buffer.toString('base64'),
        sizeBytes: buffer.length,
        mimeType: exportMimeType,
        revisionId,
        modifiedTime: revision.modifiedTime,
        isExported: true,
      };
    }

    // For regular files, download directly
    const response = await this.drive.revisions.get({
      fileId,
      revisionId,
      alt: 'media',
    }, { responseType: 'arraybuffer' });
    const buffer = Buffer.from(response.data);

    return {
      content: buffer,
      contentBase64: buffer.toString('base64'),
      sizeBytes: buffer.length,
      mimeType: revision.mimeType,
      revisionId,
      modifiedTime: revision.modifiedTime,
      isExported: false,
    };
  }

  /**
   * Format revision for display
   */
  static formatRevision(revision) {
    return {
      id: revision.id,
      mimeType: revision.mimeType,
      modifiedTime: revision.modifiedTime,
      size: revision.size ? DriveAPI.formatSize(parseInt(revision.size)) : null,
      sizeBytes: revision.size ? parseInt(revision.size) : null,
      keepForever: revision.keepForever || false,
      published: revision.published || false,
      publishAuto: revision.publishAuto || false,
      publishedOutsideDomain: revision.publishedOutsideDomain || false,
      lastModifyingUser: revision.lastModifyingUser?.displayName || revision.lastModifyingUser?.emailAddress || null,
      originalFilename: revision.originalFilename || null,
      exportLinks: revision.exportLinks || null,
    };
  }

  // ===== HELPER METHODS =====

  /**
   * Format file for display
   */
  static formatFile(file) {
    return {
      id: file.id,
      name: file.name,
      mimeType: file.mimeType,
      type: DriveAPI.getFileType(file.mimeType),
      size: file.size ? DriveAPI.formatSize(parseInt(file.size)) : null,
      sizeBytes: file.size ? parseInt(file.size) : null,
      createdTime: file.createdTime,
      modifiedTime: file.modifiedTime,
      webViewLink: file.webViewLink,
      owners: file.owners?.map(o => o.emailAddress),
      shared: file.shared || false,
      starred: file.starred || false,
      trashed: file.trashed || false,
      description: file.description,
      driveId: file.driveId || null,  // Shared Drive ID if in a Shared Drive
    };
  }

  /**
   * Get human-readable file type
   */
  static getFileType(mimeType) {
    if (!mimeType) return 'unknown';

    if (mimeType === 'application/vnd.google-apps.folder') return 'folder';
    if (mimeType === 'application/vnd.google-apps.document') return 'Google Doc';
    if (mimeType === 'application/vnd.google-apps.spreadsheet') return 'Google Sheet';
    if (mimeType === 'application/vnd.google-apps.presentation') return 'Google Slides';
    if (mimeType === 'application/vnd.google-apps.form') return 'Google Form';
    if (mimeType === 'application/vnd.google-apps.drawing') return 'Google Drawing';
    if (mimeType === 'application/pdf') return 'PDF';
    if (mimeType.startsWith('image/')) return 'Image';
    if (mimeType.startsWith('video/')) return 'Video';
    if (mimeType.startsWith('audio/')) return 'Audio';
    if (mimeType.startsWith('text/')) return 'Text';
    if (mimeType.includes('word')) return 'Word Document';
    if (mimeType.includes('excel') || mimeType.includes('spreadsheet')) return 'Spreadsheet';
    if (mimeType.includes('powerpoint') || mimeType.includes('presentation')) return 'Presentation';

    return mimeType.split('/').pop() || 'file';
  }

  /**
   * Format file size for display
   */
  static formatSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  }
}
