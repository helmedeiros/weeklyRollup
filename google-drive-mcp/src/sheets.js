/**
 * Google Sheets API Wrapper
 * Provides complete control over spreadsheet operations
 */

import { google } from 'googleapis';

export class SheetsAPI {
  constructor(authClient) {
    this.sheets = google.sheets({ version: 'v4', auth: authClient });
  }

  // ===== HELPER METHODS =====

  /**
   * Get sheet ID from sheet name or index
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {string|number} sheetIdentifier - Sheet name or index
   * @returns {Object} { sheetId, title, index }
   */
  async getSheetInfo(spreadsheetId, sheetIdentifier) {
    const spreadsheet = await this.getSpreadsheet(spreadsheetId);

    let targetSheet;
    if (typeof sheetIdentifier === 'number') {
      targetSheet = spreadsheet.sheets.find(s => s.properties.index === sheetIdentifier);
    } else {
      targetSheet = spreadsheet.sheets.find(
        s => s.properties.title.toLowerCase() === sheetIdentifier.toLowerCase()
      );
    }

    if (!targetSheet) {
      throw new Error(`Sheet "${sheetIdentifier}" not found in spreadsheet`);
    }

    return {
      sheetId: targetSheet.properties.sheetId,
      title: targetSheet.properties.title,
      index: targetSheet.properties.index,
    };
  }

  /**
   * Execute a batchUpdate request
   */
  async batchUpdate(spreadsheetId, requests) {
    const response = await this.sheets.spreadsheets.batchUpdate({
      spreadsheetId,
      requestBody: { requests },
    });
    return response.data;
  }

  /**
   * Get spreadsheet metadata including all sheet names
   * @param {string} spreadsheetId - The spreadsheet ID
   */
  async getSpreadsheet(spreadsheetId) {
    const response = await this.sheets.spreadsheets.get({
      spreadsheetId,
      fields: 'spreadsheetId,properties.title,sheets.properties',
    });
    return response.data;
  }

  /**
   * List all sheets in a spreadsheet
   * @param {string} spreadsheetId - The spreadsheet ID
   */
  async listSheets(spreadsheetId) {
    const spreadsheet = await this.getSpreadsheet(spreadsheetId);

    return {
      spreadsheetId: spreadsheet.spreadsheetId,
      title: spreadsheet.properties.title,
      sheets: spreadsheet.sheets.map(sheet => ({
        sheetId: sheet.properties.sheetId,
        title: sheet.properties.title,
        index: sheet.properties.index,
        sheetType: sheet.properties.sheetType,
        rowCount: sheet.properties.gridProperties?.rowCount,
        columnCount: sheet.properties.gridProperties?.columnCount,
      })),
    };
  }

  /**
   * Get values from a specific sheet or range
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {string} range - The A1 notation range (e.g., "Sheet1!A1:D10" or just "Sheet1")
   * @param {Object} options - Additional options
   */
  async getSheetValues(spreadsheetId, range, options = {}) {
    const {
      majorDimension = 'ROWS',
      valueRenderOption = 'FORMATTED_VALUE',
      dateTimeRenderOption = 'FORMATTED_STRING',
    } = options;

    const response = await this.sheets.spreadsheets.values.get({
      spreadsheetId,
      range,
      majorDimension,
      valueRenderOption,
      dateTimeRenderOption,
    });

    return {
      spreadsheetId: response.data.spreadsheetId,
      range: response.data.range,
      majorDimension: response.data.majorDimension,
      values: response.data.values || [],
    };
  }

  /**
   * Get values from multiple ranges
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {string[]} ranges - Array of A1 notation ranges
   */
  async batchGetValues(spreadsheetId, ranges) {
    const response = await this.sheets.spreadsheets.values.batchGet({
      spreadsheetId,
      ranges,
      valueRenderOption: 'FORMATTED_VALUE',
      dateTimeRenderOption: 'FORMATTED_STRING',
    });

    return {
      spreadsheetId: response.data.spreadsheetId,
      valueRanges: response.data.valueRanges?.map(vr => ({
        range: vr.range,
        values: vr.values || [],
      })) || [],
    };
  }

  // ===== WRITE OPERATIONS =====

  /**
   * Update values in a specific range
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {string} range - A1 notation range (e.g., "Sheet1!A1:C3")
   * @param {Array<Array<any>>} values - 2D array of values
   * @param {Object} options - Additional options
   */
  async updateValues(spreadsheetId, range, values, options = {}) {
    const { valueInputOption = 'USER_ENTERED' } = options;

    const response = await this.sheets.spreadsheets.values.update({
      spreadsheetId,
      range,
      valueInputOption,
      requestBody: { values },
    });

    return {
      spreadsheetId: response.data.spreadsheetId,
      updatedRange: response.data.updatedRange,
      updatedRows: response.data.updatedRows,
      updatedColumns: response.data.updatedColumns,
      updatedCells: response.data.updatedCells,
    };
  }

  /**
   * Append rows to the end of a sheet
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {string} range - A1 notation range (e.g., "Sheet1" or "Sheet1!A:Z")
   * @param {Array<Array<any>>} values - 2D array of rows to append
   * @param {Object} options - Additional options
   */
  async appendRows(spreadsheetId, range, values, options = {}) {
    const {
      valueInputOption = 'USER_ENTERED',
      insertDataOption = 'INSERT_ROWS',
    } = options;

    const response = await this.sheets.spreadsheets.values.append({
      spreadsheetId,
      range,
      valueInputOption,
      insertDataOption,
      requestBody: { values },
    });

    return {
      spreadsheetId: response.data.spreadsheetId,
      tableRange: response.data.tableRange,
      updatedRange: response.data.updates?.updatedRange,
      updatedRows: response.data.updates?.updatedRows,
      updatedCells: response.data.updates?.updatedCells,
    };
  }

  /**
   * Clear values from a range (keeps formatting)
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {string} range - A1 notation range to clear
   */
  async clearValues(spreadsheetId, range) {
    const response = await this.sheets.spreadsheets.values.clear({
      spreadsheetId,
      range,
    });

    return {
      spreadsheetId: response.data.spreadsheetId,
      clearedRange: response.data.clearedRange,
    };
  }

  // ===== ROW/COLUMN OPERATIONS =====

  /**
   * Insert empty rows
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {string|number} sheet - Sheet name or index
   * @param {number} startIndex - Row index to insert at (0-based)
   * @param {number} numRows - Number of rows to insert
   */
  async insertRows(spreadsheetId, sheet, startIndex, numRows) {
    const sheetInfo = await this.getSheetInfo(spreadsheetId, sheet);

    await this.batchUpdate(spreadsheetId, [{
      insertDimension: {
        range: {
          sheetId: sheetInfo.sheetId,
          dimension: 'ROWS',
          startIndex,
          endIndex: startIndex + numRows,
        },
        inheritFromBefore: startIndex > 0,
      },
    }]);

    return {
      sheet: sheetInfo.title,
      insertedAt: startIndex,
      rowsInserted: numRows,
    };
  }

  /**
   * Insert empty columns
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {string|number} sheet - Sheet name or index
   * @param {number} startIndex - Column index to insert at (0-based, A=0)
   * @param {number} numColumns - Number of columns to insert
   */
  async insertColumns(spreadsheetId, sheet, startIndex, numColumns) {
    const sheetInfo = await this.getSheetInfo(spreadsheetId, sheet);

    await this.batchUpdate(spreadsheetId, [{
      insertDimension: {
        range: {
          sheetId: sheetInfo.sheetId,
          dimension: 'COLUMNS',
          startIndex,
          endIndex: startIndex + numColumns,
        },
        inheritFromBefore: startIndex > 0,
      },
    }]);

    return {
      sheet: sheetInfo.title,
      insertedAt: startIndex,
      columnsInserted: numColumns,
    };
  }

  /**
   * Delete rows
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {string|number} sheet - Sheet name or index
   * @param {number} startIndex - First row to delete (0-based)
   * @param {number} numRows - Number of rows to delete
   */
  async deleteRows(spreadsheetId, sheet, startIndex, numRows) {
    const sheetInfo = await this.getSheetInfo(spreadsheetId, sheet);

    await this.batchUpdate(spreadsheetId, [{
      deleteDimension: {
        range: {
          sheetId: sheetInfo.sheetId,
          dimension: 'ROWS',
          startIndex,
          endIndex: startIndex + numRows,
        },
      },
    }]);

    return {
      sheet: sheetInfo.title,
      deletedFrom: startIndex,
      rowsDeleted: numRows,
    };
  }

  /**
   * Delete columns
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {string|number} sheet - Sheet name or index
   * @param {number} startIndex - First column to delete (0-based, A=0)
   * @param {number} numColumns - Number of columns to delete
   */
  async deleteColumns(spreadsheetId, sheet, startIndex, numColumns) {
    const sheetInfo = await this.getSheetInfo(spreadsheetId, sheet);

    await this.batchUpdate(spreadsheetId, [{
      deleteDimension: {
        range: {
          sheetId: sheetInfo.sheetId,
          dimension: 'COLUMNS',
          startIndex,
          endIndex: startIndex + numColumns,
        },
      },
    }]);

    return {
      sheet: sheetInfo.title,
      deletedFrom: startIndex,
      columnsDeleted: numColumns,
    };
  }

  // ===== SHEET MANAGEMENT =====

  /**
   * Add a new sheet (tab) to the spreadsheet
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {string} title - Name for the new sheet
   * @param {Object} options - Additional options (index, rowCount, columnCount)
   */
  async addSheet(spreadsheetId, title, options = {}) {
    const { index, rowCount = 1000, columnCount = 26 } = options;

    const properties = {
      title,
      gridProperties: { rowCount, columnCount },
    };
    if (index !== undefined) properties.index = index;

    const response = await this.batchUpdate(spreadsheetId, [{
      addSheet: { properties },
    }]);

    const newSheet = response.replies[0].addSheet.properties;
    return {
      sheetId: newSheet.sheetId,
      title: newSheet.title,
      index: newSheet.index,
    };
  }

  /**
   * Delete a sheet (tab) from the spreadsheet
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {string|number} sheet - Sheet name or index to delete
   */
  async deleteSheet(spreadsheetId, sheet) {
    const sheetInfo = await this.getSheetInfo(spreadsheetId, sheet);

    await this.batchUpdate(spreadsheetId, [{
      deleteSheet: { sheetId: sheetInfo.sheetId },
    }]);

    return {
      deleted: sheetInfo.title,
      sheetId: sheetInfo.sheetId,
    };
  }

  /**
   * Rename a sheet
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {string|number} sheet - Current sheet name or index
   * @param {string} newTitle - New name for the sheet
   */
  async renameSheet(spreadsheetId, sheet, newTitle) {
    const sheetInfo = await this.getSheetInfo(spreadsheetId, sheet);

    await this.batchUpdate(spreadsheetId, [{
      updateSheetProperties: {
        properties: {
          sheetId: sheetInfo.sheetId,
          title: newTitle,
        },
        fields: 'title',
      },
    }]);

    return {
      sheetId: sheetInfo.sheetId,
      oldTitle: sheetInfo.title,
      newTitle,
    };
  }

  /**
   * Duplicate a sheet within the same spreadsheet
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {string|number} sheet - Sheet to duplicate
   * @param {string} newTitle - Name for the duplicate (optional)
   */
  async duplicateSheet(spreadsheetId, sheet, newTitle = null) {
    const sheetInfo = await this.getSheetInfo(spreadsheetId, sheet);

    const request = {
      duplicateSheet: {
        sourceSheetId: sheetInfo.sheetId,
      },
    };
    if (newTitle) request.duplicateSheet.newSheetName = newTitle;

    const response = await this.batchUpdate(spreadsheetId, [request]);
    const newSheet = response.replies[0].duplicateSheet.properties;

    return {
      sourceSheet: sheetInfo.title,
      newSheetId: newSheet.sheetId,
      newTitle: newSheet.title,
      newIndex: newSheet.index,
    };
  }

  /**
   * Copy a sheet to another spreadsheet
   * @param {string} spreadsheetId - Source spreadsheet ID
   * @param {string|number} sheet - Sheet to copy
   * @param {string} destinationSpreadsheetId - Target spreadsheet ID
   */
  async copySheetTo(spreadsheetId, sheet, destinationSpreadsheetId) {
    const sheetInfo = await this.getSheetInfo(spreadsheetId, sheet);

    const response = await this.sheets.spreadsheets.sheets.copyTo({
      spreadsheetId,
      sheetId: sheetInfo.sheetId,
      requestBody: { destinationSpreadsheetId },
    });

    return {
      sourceSheet: sheetInfo.title,
      destinationSpreadsheetId,
      newSheetId: response.data.sheetId,
      newTitle: response.data.title,
    };
  }

  // ===== FORMATTING =====

  /**
   * Format cells in a range
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {string|number} sheet - Sheet name or index
   * @param {Object} range - { startRowIndex, endRowIndex, startColumnIndex, endColumnIndex }
   * @param {Object} format - Formatting options
   */
  async formatCells(spreadsheetId, sheet, range, format) {
    const sheetInfo = await this.getSheetInfo(spreadsheetId, sheet);

    const cellFormat = {};

    // Text formatting
    if (format.bold !== undefined || format.italic !== undefined ||
        format.fontSize !== undefined || format.fontFamily !== undefined) {
      cellFormat.textFormat = {};
      if (format.bold !== undefined) cellFormat.textFormat.bold = format.bold;
      if (format.italic !== undefined) cellFormat.textFormat.italic = format.italic;
      if (format.fontSize !== undefined) cellFormat.textFormat.fontSize = format.fontSize;
      if (format.fontFamily !== undefined) cellFormat.textFormat.fontFamily = format.fontFamily;
      if (format.textColor) {
        cellFormat.textFormat.foregroundColor = this._parseColor(format.textColor);
      }
    }

    // Background color
    if (format.backgroundColor) {
      cellFormat.backgroundColor = this._parseColor(format.backgroundColor);
    }

    // Horizontal alignment
    if (format.horizontalAlignment) {
      cellFormat.horizontalAlignment = format.horizontalAlignment.toUpperCase();
    }

    // Vertical alignment
    if (format.verticalAlignment) {
      cellFormat.verticalAlignment = format.verticalAlignment.toUpperCase();
    }

    // Number format
    if (format.numberFormat) {
      cellFormat.numberFormat = {
        type: format.numberFormat.type || 'NUMBER',
        pattern: format.numberFormat.pattern,
      };
    }

    // Wrap strategy
    if (format.wrapStrategy) {
      cellFormat.wrapStrategy = format.wrapStrategy.toUpperCase();
    }

    const fields = Object.keys(cellFormat).map(k => `userEnteredFormat.${k}`).join(',');

    await this.batchUpdate(spreadsheetId, [{
      repeatCell: {
        range: {
          sheetId: sheetInfo.sheetId,
          ...range,
        },
        cell: { userEnteredFormat: cellFormat },
        fields,
      },
    }]);

    return {
      sheet: sheetInfo.title,
      range,
      appliedFormat: format,
    };
  }

  /**
   * Get cell formatting from a range
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {string} range - A1 notation range (e.g., "Sheet1!A1:B5" or "A1:B5")
   * @returns {Object} Cell formatting data
   */
  async getCellFormat(spreadsheetId, range) {
    const response = await this.sheets.spreadsheets.get({
      spreadsheetId,
      ranges: [range],
      includeGridData: true,
    });

    const sheet = response.data.sheets[0];
    const sheetTitle = sheet.properties.title;
    const gridData = sheet.data[0];

    if (!gridData || !gridData.rowData) {
      return {
        spreadsheetId,
        sheet: sheetTitle,
        range,
        cells: [],
        message: 'No data found in range',
      };
    }

    // Extract formatting from each cell
    const cells = [];
    const startRow = gridData.startRow || 0;
    const startCol = gridData.startColumn || 0;

    for (let rowIdx = 0; rowIdx < gridData.rowData.length; rowIdx++) {
      const row = gridData.rowData[rowIdx];
      if (!row.values) continue;

      for (let colIdx = 0; colIdx < row.values.length; colIdx++) {
        const cell = row.values[colIdx];
        const format = cell.effectiveFormat || {};
        const userFormat = cell.userEnteredFormat || {};

        // Convert Google's format to our user-friendly format
        const cellFormat = {
          row: startRow + rowIdx,
          column: startCol + colIdx,
          cellRef: this._toCellRef(startCol + colIdx, startRow + rowIdx),
          value: cell.formattedValue || null,
        };

        // Text formatting
        if (format.textFormat) {
          const tf = format.textFormat;
          if (tf.bold) cellFormat.bold = true;
          if (tf.italic) cellFormat.italic = true;
          if (tf.strikethrough) cellFormat.strikethrough = true;
          if (tf.underline) cellFormat.underline = true;
          if (tf.fontSize) cellFormat.fontSize = tf.fontSize;
          if (tf.fontFamily) cellFormat.fontFamily = tf.fontFamily;
          if (tf.foregroundColor) {
            cellFormat.textColor = this._colorToHex(tf.foregroundColor);
          }
        }

        // Background color
        if (format.backgroundColor) {
          cellFormat.backgroundColor = this._colorToHex(format.backgroundColor);
        }

        // Alignment
        if (format.horizontalAlignment) {
          cellFormat.horizontalAlignment = format.horizontalAlignment;
        }
        if (format.verticalAlignment) {
          cellFormat.verticalAlignment = format.verticalAlignment;
        }

        // Number format
        if (format.numberFormat && format.numberFormat.type !== 'NONE') {
          cellFormat.numberFormat = {
            type: format.numberFormat.type,
            pattern: format.numberFormat.pattern,
          };
        }

        // Wrap strategy
        if (format.wrapStrategy) {
          cellFormat.wrapStrategy = format.wrapStrategy;
        }

        // Borders
        if (format.borders) {
          cellFormat.borders = {};
          for (const side of ['top', 'bottom', 'left', 'right']) {
            if (format.borders[side]) {
              cellFormat.borders[side] = {
                style: format.borders[side].style,
                color: this._colorToHex(format.borders[side].color),
              };
            }
          }
        }

        cells.push(cellFormat);
      }
    }

    // Also provide a summary of unique formats for easy reuse
    const formatSummary = this._extractFormatSummary(cells);

    return {
      spreadsheetId,
      sheet: sheetTitle,
      range,
      cells,
      formatSummary,
    };
  }

  /**
   * Convert column/row indices to A1 cell reference
   */
  _toCellRef(colIndex, rowIndex) {
    let colRef = '';
    let col = colIndex;
    while (col >= 0) {
      colRef = String.fromCharCode(65 + (col % 26)) + colRef;
      col = Math.floor(col / 26) - 1;
    }
    return colRef + (rowIndex + 1);
  }

  /**
   * Convert Google's color format to hex string
   */
  _colorToHex(color) {
    if (!color) return null;
    const r = Math.round((color.red || 0) * 255);
    const g = Math.round((color.green || 0) * 255);
    const b = Math.round((color.blue || 0) * 255);
    return '#' + [r, g, b].map(x => x.toString(16).padStart(2, '0')).join('').toUpperCase();
  }

  /**
   * Extract a summary of unique formats from cells
   */
  _extractFormatSummary(cells) {
    const summary = {
      hasBold: cells.some(c => c.bold),
      hasItalic: cells.some(c => c.italic),
      fontSizes: [...new Set(cells.filter(c => c.fontSize).map(c => c.fontSize))],
      fontFamilies: [...new Set(cells.filter(c => c.fontFamily).map(c => c.fontFamily))],
      backgroundColors: [...new Set(cells.filter(c => c.backgroundColor).map(c => c.backgroundColor))],
      textColors: [...new Set(cells.filter(c => c.textColor).map(c => c.textColor))],
      alignments: [...new Set(cells.filter(c => c.horizontalAlignment).map(c => c.horizontalAlignment))],
    };
    return summary;
  }

  /**
   * Parse color from hex string or RGB object
   */
  _parseColor(color) {
    if (typeof color === 'string') {
      // Parse hex color
      const hex = color.replace('#', '');
      return {
        red: parseInt(hex.substring(0, 2), 16) / 255,
        green: parseInt(hex.substring(2, 4), 16) / 255,
        blue: parseInt(hex.substring(4, 6), 16) / 255,
      };
    }
    return color; // Assume it's already in Google's format
  }

  /**
   * Merge cells in a range
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {string|number} sheet - Sheet name or index
   * @param {Object} range - { startRowIndex, endRowIndex, startColumnIndex, endColumnIndex }
   * @param {string} mergeType - MERGE_ALL, MERGE_COLUMNS, or MERGE_ROWS
   */
  async mergeCells(spreadsheetId, sheet, range, mergeType = 'MERGE_ALL') {
    const sheetInfo = await this.getSheetInfo(spreadsheetId, sheet);

    await this.batchUpdate(spreadsheetId, [{
      mergeCells: {
        range: {
          sheetId: sheetInfo.sheetId,
          ...range,
        },
        mergeType,
      },
    }]);

    return {
      sheet: sheetInfo.title,
      range,
      mergeType,
    };
  }

  /**
   * Unmerge cells in a range
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {string|number} sheet - Sheet name or index
   * @param {Object} range - { startRowIndex, endRowIndex, startColumnIndex, endColumnIndex }
   */
  async unmergeCells(spreadsheetId, sheet, range) {
    const sheetInfo = await this.getSheetInfo(spreadsheetId, sheet);

    await this.batchUpdate(spreadsheetId, [{
      unmergeCells: {
        range: {
          sheetId: sheetInfo.sheetId,
          ...range,
        },
      },
    }]);

    return {
      sheet: sheetInfo.title,
      range,
    };
  }

  /**
   * Resize columns
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {string|number} sheet - Sheet name or index
   * @param {number} startIndex - First column (0-based)
   * @param {number} endIndex - Last column + 1
   * @param {number} pixelSize - Width in pixels
   */
  async resizeColumns(spreadsheetId, sheet, startIndex, endIndex, pixelSize) {
    const sheetInfo = await this.getSheetInfo(spreadsheetId, sheet);

    await this.batchUpdate(spreadsheetId, [{
      updateDimensionProperties: {
        range: {
          sheetId: sheetInfo.sheetId,
          dimension: 'COLUMNS',
          startIndex,
          endIndex,
        },
        properties: { pixelSize },
        fields: 'pixelSize',
      },
    }]);

    return {
      sheet: sheetInfo.title,
      columns: `${startIndex}-${endIndex - 1}`,
      width: pixelSize,
    };
  }

  /**
   * Resize rows
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {string|number} sheet - Sheet name or index
   * @param {number} startIndex - First row (0-based)
   * @param {number} endIndex - Last row + 1
   * @param {number} pixelSize - Height in pixels
   */
  async resizeRows(spreadsheetId, sheet, startIndex, endIndex, pixelSize) {
    const sheetInfo = await this.getSheetInfo(spreadsheetId, sheet);

    await this.batchUpdate(spreadsheetId, [{
      updateDimensionProperties: {
        range: {
          sheetId: sheetInfo.sheetId,
          dimension: 'ROWS',
          startIndex,
          endIndex,
        },
        properties: { pixelSize },
        fields: 'pixelSize',
      },
    }]);

    return {
      sheet: sheetInfo.title,
      rows: `${startIndex}-${endIndex - 1}`,
      height: pixelSize,
    };
  }

  /**
   * Auto-resize columns to fit content
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {string|number} sheet - Sheet name or index
   * @param {number} startIndex - First column (0-based)
   * @param {number} endIndex - Last column + 1
   */
  async autoResizeColumns(spreadsheetId, sheet, startIndex, endIndex) {
    const sheetInfo = await this.getSheetInfo(spreadsheetId, sheet);

    await this.batchUpdate(spreadsheetId, [{
      autoResizeDimensions: {
        dimensions: {
          sheetId: sheetInfo.sheetId,
          dimension: 'COLUMNS',
          startIndex,
          endIndex,
        },
      },
    }]);

    return {
      sheet: sheetInfo.title,
      columns: `${startIndex}-${endIndex - 1}`,
      autoResized: true,
    };
  }

  // ===== FREEZE OPERATIONS =====

  /**
   * Freeze top N rows
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {string|number} sheet - Sheet name or index
   * @param {number} numRows - Number of rows to freeze (0 to unfreeze)
   */
  async freezeRows(spreadsheetId, sheet, numRows) {
    const sheetInfo = await this.getSheetInfo(spreadsheetId, sheet);

    await this.batchUpdate(spreadsheetId, [{
      updateSheetProperties: {
        properties: {
          sheetId: sheetInfo.sheetId,
          gridProperties: {
            frozenRowCount: numRows,
          },
        },
        fields: 'gridProperties.frozenRowCount',
      },
    }]);

    return {
      sheet: sheetInfo.title,
      frozenRows: numRows,
    };
  }

  /**
   * Freeze left N columns
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {string|number} sheet - Sheet name or index
   * @param {number} numColumns - Number of columns to freeze (0 to unfreeze)
   */
  async freezeColumns(spreadsheetId, sheet, numColumns) {
    const sheetInfo = await this.getSheetInfo(spreadsheetId, sheet);

    await this.batchUpdate(spreadsheetId, [{
      updateSheetProperties: {
        properties: {
          sheetId: sheetInfo.sheetId,
          gridProperties: {
            frozenColumnCount: numColumns,
          },
        },
        fields: 'gridProperties.frozenColumnCount',
      },
    }]);

    return {
      sheet: sheetInfo.title,
      frozenColumns: numColumns,
    };
  }

  /**
   * Remove all frozen rows and columns
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {string|number} sheet - Sheet name or index
   */
  async unfreeze(spreadsheetId, sheet) {
    const sheetInfo = await this.getSheetInfo(spreadsheetId, sheet);

    await this.batchUpdate(spreadsheetId, [{
      updateSheetProperties: {
        properties: {
          sheetId: sheetInfo.sheetId,
          gridProperties: {
            frozenRowCount: 0,
            frozenColumnCount: 0,
          },
        },
        fields: 'gridProperties.frozenRowCount,gridProperties.frozenColumnCount',
      },
    }]);

    return {
      sheet: sheetInfo.title,
      frozenRows: 0,
      frozenColumns: 0,
    };
  }

  // ===== ADVANCED OPERATIONS =====

  /**
   * Sort a range by column(s)
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {string|number} sheet - Sheet name or index
   * @param {Object} range - { startRowIndex, endRowIndex, startColumnIndex, endColumnIndex }
   * @param {Array} sortSpecs - Array of { columnIndex, ascending } objects
   */
  async sortRange(spreadsheetId, sheet, range, sortSpecs) {
    const sheetInfo = await this.getSheetInfo(spreadsheetId, sheet);

    await this.batchUpdate(spreadsheetId, [{
      sortRange: {
        range: {
          sheetId: sheetInfo.sheetId,
          ...range,
        },
        sortSpecs: sortSpecs.map(spec => ({
          dimensionIndex: spec.columnIndex,
          sortOrder: spec.ascending !== false ? 'ASCENDING' : 'DESCENDING',
        })),
      },
    }]);

    return {
      sheet: sheetInfo.title,
      range,
      sortedBy: sortSpecs,
    };
  }

  /**
   * Find and replace text
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {string} find - Text to find
   * @param {string} replacement - Replacement text
   * @param {Object} options - Search options
   */
  async findReplace(spreadsheetId, find, replacement, options = {}) {
    const {
      sheet = null,
      matchCase = false,
      matchEntireCell = false,
      searchByRegex = false,
      allSheets = true,
    } = options;

    const request = {
      findReplace: {
        find,
        replacement,
        matchCase,
        matchEntireCell,
        searchByRegex,
        allSheets: sheet === null && allSheets,
      },
    };

    if (sheet !== null) {
      const sheetInfo = await this.getSheetInfo(spreadsheetId, sheet);
      request.findReplace.sheetId = sheetInfo.sheetId;
      request.findReplace.allSheets = false;
    }

    const response = await this.batchUpdate(spreadsheetId, [request]);
    const result = response.replies[0].findReplace;

    return {
      find,
      replacement,
      occurrencesChanged: result.occurrencesChanged || 0,
      rowsChanged: result.rowsChanged || 0,
      sheetsChanged: result.sheetsChanged || 0,
      valuesChanged: result.valuesChanged || 0,
    };
  }

  /**
   * Add data validation to cells
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {string|number} sheet - Sheet name or index
   * @param {Object} range - { startRowIndex, endRowIndex, startColumnIndex, endColumnIndex }
   * @param {Object} rule - Validation rule configuration
   */
  async setDataValidation(spreadsheetId, sheet, range, rule) {
    const sheetInfo = await this.getSheetInfo(spreadsheetId, sheet);

    const condition = {};

    if (rule.type === 'list') {
      condition.type = 'ONE_OF_LIST';
      condition.values = rule.values.map(v => ({ userEnteredValue: v }));
    } else if (rule.type === 'number') {
      condition.type = rule.operator || 'NUMBER_GREATER';
      if (rule.value !== undefined) {
        condition.values = [{ userEnteredValue: String(rule.value) }];
      }
    } else if (rule.type === 'date') {
      condition.type = rule.operator || 'DATE_AFTER';
      if (rule.value) {
        condition.values = [{ userEnteredValue: rule.value }];
      }
    } else if (rule.type === 'checkbox') {
      condition.type = 'BOOLEAN';
    } else if (rule.type === 'custom') {
      condition.type = 'CUSTOM_FORMULA';
      condition.values = [{ userEnteredValue: rule.formula }];
    }

    await this.batchUpdate(spreadsheetId, [{
      setDataValidation: {
        range: {
          sheetId: sheetInfo.sheetId,
          ...range,
        },
        rule: {
          condition,
          strict: rule.strict !== false,
          showCustomUi: rule.showDropdown !== false,
        },
      },
    }]);

    return {
      sheet: sheetInfo.title,
      range,
      validationType: rule.type,
    };
  }

  /**
   * Clear data validation from cells
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {string|number} sheet - Sheet name or index
   * @param {Object} range - { startRowIndex, endRowIndex, startColumnIndex, endColumnIndex }
   */
  async clearDataValidation(spreadsheetId, sheet, range) {
    const sheetInfo = await this.getSheetInfo(spreadsheetId, sheet);

    await this.batchUpdate(spreadsheetId, [{
      setDataValidation: {
        range: {
          sheetId: sheetInfo.sheetId,
          ...range,
        },
        rule: null,
      },
    }]);

    return {
      sheet: sheetInfo.title,
      range,
      cleared: true,
    };
  }

  /**
   * Get entire sheet content by name or index
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {string|number} sheetIdentifier - Sheet name (string) or index (number)
   */
  async getSheetContent(spreadsheetId, sheetIdentifier) {
    // First get spreadsheet metadata to find the sheet
    const spreadsheet = await this.getSpreadsheet(spreadsheetId);

    let targetSheet;
    if (typeof sheetIdentifier === 'number') {
      targetSheet = spreadsheet.sheets.find(s => s.properties.index === sheetIdentifier);
    } else {
      targetSheet = spreadsheet.sheets.find(
        s => s.properties.title.toLowerCase() === sheetIdentifier.toLowerCase()
      );
    }

    if (!targetSheet) {
      throw new Error(`Sheet "${sheetIdentifier}" not found in spreadsheet`);
    }

    const sheetName = targetSheet.properties.title;

    // Get all values from the sheet
    const values = await this.getSheetValues(spreadsheetId, sheetName);

    return {
      spreadsheetId,
      spreadsheetTitle: spreadsheet.properties.title,
      sheetId: targetSheet.properties.sheetId,
      sheetTitle: sheetName,
      sheetIndex: targetSheet.properties.index,
      rowCount: values.values.length,
      columnCount: values.values.length > 0 ? Math.max(...values.values.map(r => r.length)) : 0,
      values: values.values,
    };
  }

  /**
   * Create a new Google Spreadsheet
   * @param {string} title - Spreadsheet title
   * @param {string[]} sheetNames - Optional array of sheet names to create (default: ["Sheet1"])
   * @param {Array<Array<any>>} initialData - Optional initial data for the first sheet
   */
  async createSpreadsheet(title, sheetNames = ['Sheet1'], initialData = null) {
    const sheets = sheetNames.map((name, index) => ({
      properties: {
        title: name,
        index,
      },
    }));

    const response = await this.sheets.spreadsheets.create({
      requestBody: {
        properties: { title },
        sheets,
      },
    });

    const spreadsheet = response.data;

    // If initial data provided, write it to the first sheet
    if (initialData && initialData.length > 0) {
      await this.sheets.spreadsheets.values.update({
        spreadsheetId: spreadsheet.spreadsheetId,
        range: `${sheetNames[0]}!A1`,
        valueInputOption: 'USER_ENTERED',
        requestBody: {
          values: initialData,
        },
      });
    }

    return {
      spreadsheetId: spreadsheet.spreadsheetId,
      title: spreadsheet.properties.title,
      spreadsheetUrl: spreadsheet.spreadsheetUrl,
      sheets: spreadsheet.sheets.map(s => ({
        sheetId: s.properties.sheetId,
        title: s.properties.title,
        index: s.properties.index,
      })),
    };
  }

  /**
   * Format sheet data as a table string for display
   */
  static formatAsTable(values, maxRows = 50) {
    if (!values || values.length === 0) {
      return '(empty sheet)';
    }

    const displayValues = values.slice(0, maxRows);
    const truncated = values.length > maxRows;

    // Calculate column widths
    const colWidths = [];
    for (const row of displayValues) {
      for (let i = 0; i < row.length; i++) {
        const cellLen = String(row[i] || '').length;
        colWidths[i] = Math.min(Math.max(colWidths[i] || 0, cellLen), 40); // Max 40 chars per column
      }
    }

    // Format rows
    const lines = displayValues.map(row => {
      return row.map((cell, i) => {
        const str = String(cell || '');
        const width = colWidths[i] || 10;
        return str.length > width ? str.substring(0, width - 2) + '..' : str.padEnd(width);
      }).join(' | ');
    });

    // Add header separator after first row
    if (lines.length > 1) {
      const separator = colWidths.map(w => '-'.repeat(w)).join('-+-');
      lines.splice(1, 0, separator);
    }

    let result = lines.join('\n');
    if (truncated) {
      result += `\n... (${values.length - maxRows} more rows)`;
    }

    return result;
  }

  // ===== FILTER OPERATIONS =====

  /**
   * Set a basic filter on a sheet
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {string|number} sheet - Sheet name or index
   * @param {Object} range - Optional range { startRowIndex, endRowIndex, startColumnIndex, endColumnIndex }
   *                         If not provided, filters the entire data range
   * @param {Object} criteria - Optional filter criteria by column index
   *                           e.g., { 0: { hiddenValues: ['Draft'] }, 2: { condition: { type: 'NUMBER_GREATER', values: [{ userEnteredValue: '100' }] } } }
   */
  async setBasicFilter(spreadsheetId, sheet, range = null, criteria = null) {
    const sheetInfo = await this.getSheetInfo(spreadsheetId, sheet);

    // If no range specified, we need to get the sheet dimensions
    let filterRange;
    if (range) {
      filterRange = {
        sheetId: sheetInfo.sheetId,
        ...range,
      };
    } else {
      // Get sheet dimensions to filter entire data area
      const spreadsheet = await this.sheets.spreadsheets.get({
        spreadsheetId,
        ranges: [sheetInfo.title],
        fields: 'sheets.properties.gridProperties',
      });
      const gridProps = spreadsheet.data.sheets[0].properties.gridProperties;
      filterRange = {
        sheetId: sheetInfo.sheetId,
        startRowIndex: 0,
        endRowIndex: gridProps.rowCount,
        startColumnIndex: 0,
        endColumnIndex: gridProps.columnCount,
      };
    }

    const filterSpec = {
      range: filterRange,
    };

    // Add criteria if provided
    if (criteria) {
      filterSpec.criteria = {};
      for (const [colIndex, colCriteria] of Object.entries(criteria)) {
        filterSpec.criteria[colIndex] = this._buildFilterCriteria(colCriteria);
      }
    }

    await this.batchUpdate(spreadsheetId, [{
      setBasicFilter: {
        filter: filterSpec,
      },
    }]);

    return {
      sheet: sheetInfo.title,
      range: filterRange,
      criteria: criteria || 'none',
      message: 'Basic filter applied',
    };
  }

  /**
   * Build filter criteria from user-friendly format
   */
  _buildFilterCriteria(criteria) {
    const result = {};

    // Hidden values - hide rows with these exact values
    if (criteria.hiddenValues) {
      result.hiddenValues = criteria.hiddenValues;
    }

    // Condition-based filtering
    if (criteria.condition) {
      result.condition = {
        type: criteria.condition.type,
      };
      if (criteria.condition.values) {
        result.condition.values = criteria.condition.values.map(v => {
          if (typeof v === 'object') return v;
          return { userEnteredValue: String(v) };
        });
      }
    }

    // Filter by background color
    if (criteria.visibleBackgroundColor) {
      result.visibleBackgroundColor = this._parseColor(criteria.visibleBackgroundColor);
    }

    // Filter by text color
    if (criteria.visibleForegroundColor) {
      result.visibleForegroundColor = this._parseColor(criteria.visibleForegroundColor);
    }

    return result;
  }

  /**
   * Update filter criteria for specific columns (keeps existing filter, modifies criteria)
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {string|number} sheet - Sheet name or index
   * @param {Object} criteria - Filter criteria by column index
   */
  async updateFilterCriteria(spreadsheetId, sheet, criteria) {
    // First get the existing filter
    const existingFilter = await this.getBasicFilter(spreadsheetId, sheet);
    if (!existingFilter.hasFilter) {
      throw new Error('No existing filter to update. Use setBasicFilter first.');
    }

    // Merge criteria
    const mergedCriteria = { ...existingFilter.criteria };
    for (const [colIndex, colCriteria] of Object.entries(criteria)) {
      if (colCriteria === null) {
        // Remove criteria for this column
        delete mergedCriteria[colIndex];
      } else {
        mergedCriteria[colIndex] = this._buildFilterCriteria(colCriteria);
      }
    }

    // Re-apply filter with updated criteria
    const filterSpec = {
      range: existingFilter.range,
      criteria: mergedCriteria,
    };

    await this.batchUpdate(spreadsheetId, [{
      setBasicFilter: {
        filter: filterSpec,
      },
    }]);

    return {
      sheet: existingFilter.sheetTitle,
      range: existingFilter.range,
      updatedCriteria: criteria,
      message: 'Filter criteria updated',
    };
  }

  /**
   * Clear the basic filter from a sheet
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {string|number} sheet - Sheet name or index
   */
  async clearBasicFilter(spreadsheetId, sheet) {
    const sheetInfo = await this.getSheetInfo(spreadsheetId, sheet);

    await this.batchUpdate(spreadsheetId, [{
      clearBasicFilter: {
        sheetId: sheetInfo.sheetId,
      },
    }]);

    return {
      sheet: sheetInfo.title,
      message: 'Basic filter cleared',
    };
  }

  /**
   * Get the current basic filter configuration
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {string|number} sheet - Sheet name or index
   */
  async getBasicFilter(spreadsheetId, sheet) {
    const sheetInfo = await this.getSheetInfo(spreadsheetId, sheet);

    // Get spreadsheet with filter information
    const response = await this.sheets.spreadsheets.get({
      spreadsheetId,
      ranges: [sheetInfo.title],
      fields: 'sheets.basicFilter,sheets.properties',
    });

    const sheetData = response.data.sheets[0];
    const basicFilter = sheetData.basicFilter;

    if (!basicFilter) {
      return {
        sheetTitle: sheetInfo.title,
        hasFilter: false,
        message: 'No basic filter set on this sheet',
      };
    }

    return {
      sheetTitle: sheetInfo.title,
      hasFilter: true,
      range: basicFilter.range,
      criteria: basicFilter.criteria || {},
      sortSpecs: basicFilter.sortSpecs || [],
    };
  }

  /**
   * Add sort to an existing filter
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {string|number} sheet - Sheet name or index
   * @param {number} columnIndex - Column to sort by (0-based)
   * @param {boolean} ascending - Sort order (true = A-Z, false = Z-A)
   */
  async setFilterSort(spreadsheetId, sheet, columnIndex, ascending = true) {
    const existingFilter = await this.getBasicFilter(spreadsheetId, sheet);
    if (!existingFilter.hasFilter) {
      throw new Error('No existing filter. Use setBasicFilter first.');
    }

    const filterSpec = {
      range: existingFilter.range,
      criteria: existingFilter.criteria,
      sortSpecs: [{
        dimensionIndex: columnIndex,
        sortOrder: ascending ? 'ASCENDING' : 'DESCENDING',
      }],
    };

    await this.batchUpdate(spreadsheetId, [{
      setBasicFilter: {
        filter: filterSpec,
      },
    }]);

    return {
      sheet: existingFilter.sheetTitle,
      sortedBy: columnIndex,
      ascending,
      message: 'Filter sort applied',
    };
  }

  // ===== BORDER OPERATIONS =====

  /**
   * Update cell borders
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {string|number} sheet - Sheet name or index
   * @param {Object} range - { startRowIndex, endRowIndex, startColumnIndex, endColumnIndex }
   * @param {Object} borders - Border configuration { top, bottom, left, right, innerHorizontal, innerVertical }
   *                           Each border: { style, color, width } where style is DOTTED, DASHED, SOLID, etc.
   */
  async updateBorders(spreadsheetId, sheet, range, borders) {
    const sheetInfo = await this.getSheetInfo(spreadsheetId, sheet);

    const borderRequest = {
      range: {
        sheetId: sheetInfo.sheetId,
        ...range,
      },
    };

    // Process each border side
    const sides = ['top', 'bottom', 'left', 'right', 'innerHorizontal', 'innerVertical'];
    for (const side of sides) {
      if (borders[side]) {
        const border = borders[side];
        borderRequest[side] = {
          style: border.style || 'SOLID',
          width: border.width || 1,
        };
        if (border.color) {
          borderRequest[side].color = this._parseColor(border.color);
        }
      }
    }

    await this.batchUpdate(spreadsheetId, [{
      updateBorders: borderRequest,
    }]);

    return {
      sheet: sheetInfo.title,
      range,
      borders: Object.keys(borders),
    };
  }

  // ===== NAMED RANGE OPERATIONS =====

  /**
   * Add a named range
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {string} name - Name for the range
   * @param {string|number} sheet - Sheet name or index
   * @param {Object} range - { startRowIndex, endRowIndex, startColumnIndex, endColumnIndex }
   */
  async addNamedRange(spreadsheetId, name, sheet, range) {
    const sheetInfo = await this.getSheetInfo(spreadsheetId, sheet);

    const response = await this.batchUpdate(spreadsheetId, [{
      addNamedRange: {
        namedRange: {
          name,
          range: {
            sheetId: sheetInfo.sheetId,
            ...range,
          },
        },
      },
    }]);

    const namedRangeId = response.replies[0].addNamedRange.namedRange.namedRangeId;
    return {
      namedRangeId,
      name,
      sheet: sheetInfo.title,
      range,
    };
  }

  /**
   * Delete a named range
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {string} namedRangeId - The ID of the named range to delete
   */
  async deleteNamedRange(spreadsheetId, namedRangeId) {
    await this.batchUpdate(spreadsheetId, [{
      deleteNamedRange: { namedRangeId },
    }]);

    return {
      deleted: namedRangeId,
    };
  }

  /**
   * Get all named ranges in a spreadsheet
   * @param {string} spreadsheetId - The spreadsheet ID
   */
  async getNamedRanges(spreadsheetId) {
    const response = await this.sheets.spreadsheets.get({
      spreadsheetId,
      fields: 'namedRanges',
    });

    return {
      namedRanges: response.data.namedRanges || [],
    };
  }

  // ===== CONDITIONAL FORMATTING =====

  /**
   * Add a conditional format rule
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {string|number} sheet - Sheet name or index
   * @param {Object} range - { startRowIndex, endRowIndex, startColumnIndex, endColumnIndex }
   * @param {Object} rule - Rule configuration
   *   - type: 'boolean' | 'gradient'
   *   - For boolean rules:
   *     - condition: { type: 'TEXT_CONTAINS' | 'NUMBER_GREATER' | etc., values: [{userEnteredValue: 'text'}] }
   *     - format: { backgroundColor, textFormat, etc. }
   *   - For gradient rules:
   *     - minpoint, midpoint, maxpoint: { type: 'MIN' | 'MAX' | 'NUMBER' | 'PERCENT', value?, color }
   * @param {number} index - Optional index for rule order (0 = highest priority)
   */
  async addConditionalFormatRule(spreadsheetId, sheet, range, rule, index = 0) {
    const sheetInfo = await this.getSheetInfo(spreadsheetId, sheet);

    const formatRule = {
      ranges: [{
        sheetId: sheetInfo.sheetId,
        ...range,
      }],
    };

    if (rule.type === 'gradient') {
      formatRule.gradientRule = {};
      if (rule.minpoint) {
        formatRule.gradientRule.minpoint = {
          type: rule.minpoint.type || 'MIN',
          color: this._parseColor(rule.minpoint.color),
        };
        if (rule.minpoint.value !== undefined) {
          formatRule.gradientRule.minpoint.value = String(rule.minpoint.value);
        }
      }
      if (rule.midpoint) {
        formatRule.gradientRule.midpoint = {
          type: rule.midpoint.type || 'PERCENTILE',
          value: String(rule.midpoint.value || 50),
          color: this._parseColor(rule.midpoint.color),
        };
      }
      if (rule.maxpoint) {
        formatRule.gradientRule.maxpoint = {
          type: rule.maxpoint.type || 'MAX',
          color: this._parseColor(rule.maxpoint.color),
        };
        if (rule.maxpoint.value !== undefined) {
          formatRule.gradientRule.maxpoint.value = String(rule.maxpoint.value);
        }
      }
    } else {
      // Boolean rule
      formatRule.booleanRule = {
        condition: {
          type: rule.condition?.type || 'NOT_BLANK',
        },
        format: {},
      };
      if (rule.condition?.values) {
        formatRule.booleanRule.condition.values = rule.condition.values.map(v => ({
          userEnteredValue: typeof v === 'object' ? v.userEnteredValue : String(v),
        }));
      }
      if (rule.format?.backgroundColor) {
        formatRule.booleanRule.format.backgroundColor = this._parseColor(rule.format.backgroundColor);
      }
      if (rule.format?.textFormat) {
        formatRule.booleanRule.format.textFormat = rule.format.textFormat;
      }
    }

    await this.batchUpdate(spreadsheetId, [{
      addConditionalFormatRule: {
        rule: formatRule,
        index,
      },
    }]);

    return {
      sheet: sheetInfo.title,
      range,
      ruleType: rule.type || 'boolean',
      index,
    };
  }

  /**
   * Delete a conditional format rule
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {string|number} sheet - Sheet name or index
   * @param {number} index - The index of the rule to delete (0-based)
   */
  async deleteConditionalFormatRule(spreadsheetId, sheet, index) {
    const sheetInfo = await this.getSheetInfo(spreadsheetId, sheet);

    await this.batchUpdate(spreadsheetId, [{
      deleteConditionalFormatRule: {
        sheetId: sheetInfo.sheetId,
        index,
      },
    }]);

    return {
      sheet: sheetInfo.title,
      deletedIndex: index,
    };
  }

  /**
   * Get conditional format rules for a sheet
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {string|number} sheet - Sheet name or index
   */
  async getConditionalFormatRules(spreadsheetId, sheet) {
    const sheetInfo = await this.getSheetInfo(spreadsheetId, sheet);

    const response = await this.sheets.spreadsheets.get({
      spreadsheetId,
      ranges: [sheetInfo.title],
      fields: 'sheets.conditionalFormats',
    });

    return {
      sheet: sheetInfo.title,
      rules: response.data.sheets[0]?.conditionalFormats || [],
    };
  }

  // ===== PROTECTED RANGES =====

  /**
   * Add a protected range
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {string|number} sheet - Sheet name or index
   * @param {Object} range - { startRowIndex, endRowIndex, startColumnIndex, endColumnIndex }
   *                         If null, protects the entire sheet
   * @param {Object} options - { description, warningOnly, editors }
   */
  async addProtectedRange(spreadsheetId, sheet, range = null, options = {}) {
    const sheetInfo = await this.getSheetInfo(spreadsheetId, sheet);

    const protectedRange = {
      description: options.description || 'Protected range',
      warningOnly: options.warningOnly || false,
    };

    if (range) {
      protectedRange.range = {
        sheetId: sheetInfo.sheetId,
        ...range,
      };
    } else {
      protectedRange.range = {
        sheetId: sheetInfo.sheetId,
      };
    }

    if (options.editors) {
      protectedRange.editors = {
        users: options.editors,
      };
    }

    const response = await this.batchUpdate(spreadsheetId, [{
      addProtectedRange: { protectedRange },
    }]);

    const protectedRangeId = response.replies[0].addProtectedRange.protectedRange.protectedRangeId;
    return {
      protectedRangeId,
      sheet: sheetInfo.title,
      range: range || 'entire sheet',
      description: options.description,
      warningOnly: options.warningOnly || false,
    };
  }

  /**
   * Delete a protected range
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {number} protectedRangeId - The ID of the protected range to delete
   */
  async deleteProtectedRange(spreadsheetId, protectedRangeId) {
    await this.batchUpdate(spreadsheetId, [{
      deleteProtectedRange: { protectedRangeId },
    }]);

    return {
      deleted: protectedRangeId,
    };
  }

  /**
   * Get protected ranges in a sheet
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {string|number} sheet - Sheet name or index
   */
  async getProtectedRanges(spreadsheetId, sheet) {
    const sheetInfo = await this.getSheetInfo(spreadsheetId, sheet);

    const response = await this.sheets.spreadsheets.get({
      spreadsheetId,
      ranges: [sheetInfo.title],
      fields: 'sheets.protectedRanges',
    });

    return {
      sheet: sheetInfo.title,
      protectedRanges: response.data.sheets[0]?.protectedRanges || [],
    };
  }

  // ===== BANDING (ALTERNATING COLORS) =====

  /**
   * Add banding (alternating row colors)
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {string|number} sheet - Sheet name or index
   * @param {Object} range - { startRowIndex, endRowIndex, startColumnIndex, endColumnIndex }
   * @param {Object} options - { headerColor, firstRowColor, secondRowColor, footerColor }
   */
  async addBanding(spreadsheetId, sheet, range, options = {}) {
    const sheetInfo = await this.getSheetInfo(spreadsheetId, sheet);

    const bandingProperties = {
      range: {
        sheetId: sheetInfo.sheetId,
        ...range,
      },
      rowProperties: {},
    };

    if (options.headerColor) {
      bandingProperties.rowProperties.headerColor = this._parseColor(options.headerColor);
    }
    if (options.firstRowColor) {
      bandingProperties.rowProperties.firstBandColor = this._parseColor(options.firstRowColor);
    }
    if (options.secondRowColor) {
      bandingProperties.rowProperties.secondBandColor = this._parseColor(options.secondRowColor);
    }
    if (options.footerColor) {
      bandingProperties.rowProperties.footerColor = this._parseColor(options.footerColor);
    }

    const response = await this.batchUpdate(spreadsheetId, [{
      addBanding: { bandedRange: bandingProperties },
    }]);

    const bandedRangeId = response.replies[0].addBanding.bandedRange.bandedRangeId;
    return {
      bandedRangeId,
      sheet: sheetInfo.title,
      range,
    };
  }

  /**
   * Delete banding
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {number} bandedRangeId - The ID of the banded range to delete
   */
  async deleteBanding(spreadsheetId, bandedRangeId) {
    await this.batchUpdate(spreadsheetId, [{
      deleteBanding: { bandedRangeId },
    }]);

    return {
      deleted: bandedRangeId,
    };
  }

  // ===== DIMENSION GROUPS (COLLAPSIBLE) =====

  /**
   * Add a dimension group (collapsible rows/columns)
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {string|number} sheet - Sheet name or index
   * @param {string} dimension - 'ROWS' or 'COLUMNS'
   * @param {number} startIndex - First row/column (0-based)
   * @param {number} endIndex - Last row/column + 1
   */
  async addDimensionGroup(spreadsheetId, sheet, dimension, startIndex, endIndex) {
    const sheetInfo = await this.getSheetInfo(spreadsheetId, sheet);

    await this.batchUpdate(spreadsheetId, [{
      addDimensionGroup: {
        range: {
          sheetId: sheetInfo.sheetId,
          dimension: dimension.toUpperCase(),
          startIndex,
          endIndex,
        },
      },
    }]);

    return {
      sheet: sheetInfo.title,
      dimension,
      startIndex,
      endIndex,
    };
  }

  /**
   * Delete a dimension group
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {string|number} sheet - Sheet name or index
   * @param {string} dimension - 'ROWS' or 'COLUMNS'
   * @param {number} startIndex - First row/column (0-based)
   * @param {number} endIndex - Last row/column + 1
   */
  async deleteDimensionGroup(spreadsheetId, sheet, dimension, startIndex, endIndex) {
    const sheetInfo = await this.getSheetInfo(spreadsheetId, sheet);

    await this.batchUpdate(spreadsheetId, [{
      deleteDimensionGroup: {
        range: {
          sheetId: sheetInfo.sheetId,
          dimension: dimension.toUpperCase(),
          startIndex,
          endIndex,
        },
      },
    }]);

    return {
      sheet: sheetInfo.title,
      dimension,
      startIndex,
      endIndex,
    };
  }

  // ===== COPY/CUT/PASTE OPERATIONS =====

  /**
   * Copy and paste data
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {string|number} sourceSheet - Source sheet name or index
   * @param {Object} sourceRange - { startRowIndex, endRowIndex, startColumnIndex, endColumnIndex }
   * @param {string|number} destSheet - Destination sheet name or index
   * @param {Object} destRange - { startRowIndex, startColumnIndex } - top-left corner
   * @param {string} pasteType - PASTE_NORMAL, PASTE_VALUES, PASTE_FORMAT, PASTE_NO_BORDERS, PASTE_FORMULA, etc.
   */
  async copyPaste(spreadsheetId, sourceSheet, sourceRange, destSheet, destRange, pasteType = 'PASTE_NORMAL') {
    const sourceInfo = await this.getSheetInfo(spreadsheetId, sourceSheet);
    const destInfo = await this.getSheetInfo(spreadsheetId, destSheet);

    const rowCount = sourceRange.endRowIndex - sourceRange.startRowIndex;
    const colCount = sourceRange.endColumnIndex - sourceRange.startColumnIndex;

    await this.batchUpdate(spreadsheetId, [{
      copyPaste: {
        source: {
          sheetId: sourceInfo.sheetId,
          ...sourceRange,
        },
        destination: {
          sheetId: destInfo.sheetId,
          startRowIndex: destRange.startRowIndex,
          endRowIndex: destRange.startRowIndex + rowCount,
          startColumnIndex: destRange.startColumnIndex,
          endColumnIndex: destRange.startColumnIndex + colCount,
        },
        pasteType,
        pasteOrientation: 'NORMAL',
      },
    }]);

    return {
      sourceSheet: sourceInfo.title,
      sourceRange,
      destSheet: destInfo.title,
      destRange,
      pasteType,
    };
  }

  /**
   * Cut and paste data
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {string|number} sourceSheet - Source sheet name or index
   * @param {Object} sourceRange - { startRowIndex, endRowIndex, startColumnIndex, endColumnIndex }
   * @param {string|number} destSheet - Destination sheet name or index
   * @param {Object} destRange - { startRowIndex, startColumnIndex } - top-left corner
   * @param {string} pasteType - PASTE_NORMAL, PASTE_VALUES, etc.
   */
  async cutPaste(spreadsheetId, sourceSheet, sourceRange, destSheet, destRange, pasteType = 'PASTE_NORMAL') {
    const sourceInfo = await this.getSheetInfo(spreadsheetId, sourceSheet);
    const destInfo = await this.getSheetInfo(spreadsheetId, destSheet);

    await this.batchUpdate(spreadsheetId, [{
      cutPaste: {
        source: {
          sheetId: sourceInfo.sheetId,
          ...sourceRange,
        },
        destination: {
          sheetId: destInfo.sheetId,
          index: destRange.startRowIndex * 1000000 + destRange.startColumnIndex, // coordinate
        },
        pasteType,
      },
    }]);

    return {
      sourceSheet: sourceInfo.title,
      sourceRange,
      destSheet: destInfo.title,
      destRange,
      pasteType,
    };
  }

  // ===== DATA CLEANUP OPERATIONS =====

  /**
   * Trim whitespace from cells
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {string|number} sheet - Sheet name or index
   * @param {Object} range - { startRowIndex, endRowIndex, startColumnIndex, endColumnIndex }
   */
  async trimWhitespace(spreadsheetId, sheet, range) {
    const sheetInfo = await this.getSheetInfo(spreadsheetId, sheet);

    await this.batchUpdate(spreadsheetId, [{
      trimWhitespace: {
        range: {
          sheetId: sheetInfo.sheetId,
          ...range,
        },
      },
    }]);

    return {
      sheet: sheetInfo.title,
      range,
      message: 'Whitespace trimmed',
    };
  }

  /**
   * Delete duplicate rows
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {string|number} sheet - Sheet name or index
   * @param {Object} range - { startRowIndex, endRowIndex, startColumnIndex, endColumnIndex }
   * @param {number[]} comparisonColumns - Column indices to compare for duplicates (0-based)
   */
  async deleteDuplicates(spreadsheetId, sheet, range, comparisonColumns = null) {
    const sheetInfo = await this.getSheetInfo(spreadsheetId, sheet);

    const request = {
      deleteDuplicates: {
        range: {
          sheetId: sheetInfo.sheetId,
          ...range,
        },
      },
    };

    if (comparisonColumns && comparisonColumns.length > 0) {
      request.deleteDuplicates.comparisonColumns = comparisonColumns.map(idx => ({
        sheetId: sheetInfo.sheetId,
        dimension: 'COLUMNS',
        startIndex: idx,
        endIndex: idx + 1,
      }));
    }

    const response = await this.batchUpdate(spreadsheetId, [request]);
    const result = response.replies[0].deleteDuplicates;

    return {
      sheet: sheetInfo.title,
      range,
      duplicatesRemoved: result.duplicatesRemovedCount || 0,
    };
  }

  // ===== RANGE OPERATIONS =====

  /**
   * Insert a range (cells shift to make room)
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {string|number} sheet - Sheet name or index
   * @param {Object} range - { startRowIndex, endRowIndex, startColumnIndex, endColumnIndex }
   * @param {string} shiftDimension - 'ROWS' or 'COLUMNS'
   */
  async insertRange(spreadsheetId, sheet, range, shiftDimension = 'ROWS') {
    const sheetInfo = await this.getSheetInfo(spreadsheetId, sheet);

    await this.batchUpdate(spreadsheetId, [{
      insertRange: {
        range: {
          sheetId: sheetInfo.sheetId,
          ...range,
        },
        shiftDimension: shiftDimension.toUpperCase(),
      },
    }]);

    return {
      sheet: sheetInfo.title,
      range,
      shiftDimension,
    };
  }

  /**
   * Delete a range (cells shift to fill gap)
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {string|number} sheet - Sheet name or index
   * @param {Object} range - { startRowIndex, endRowIndex, startColumnIndex, endColumnIndex }
   * @param {string} shiftDimension - 'ROWS' or 'COLUMNS'
   */
  async deleteRange(spreadsheetId, sheet, range, shiftDimension = 'ROWS') {
    const sheetInfo = await this.getSheetInfo(spreadsheetId, sheet);

    await this.batchUpdate(spreadsheetId, [{
      deleteRange: {
        range: {
          sheetId: sheetInfo.sheetId,
          ...range,
        },
        shiftDimension: shiftDimension.toUpperCase(),
      },
    }]);

    return {
      sheet: sheetInfo.title,
      range,
      shiftDimension,
    };
  }

  // ===== DIMENSION OPERATIONS =====

  /**
   * Move rows or columns
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {string|number} sheet - Sheet name or index
   * @param {string} dimension - 'ROWS' or 'COLUMNS'
   * @param {number} startIndex - First row/column to move (0-based)
   * @param {number} endIndex - Last row/column + 1
   * @param {number} destinationIndex - Where to move to (0-based)
   */
  async moveDimension(spreadsheetId, sheet, dimension, startIndex, endIndex, destinationIndex) {
    const sheetInfo = await this.getSheetInfo(spreadsheetId, sheet);

    await this.batchUpdate(spreadsheetId, [{
      moveDimension: {
        source: {
          sheetId: sheetInfo.sheetId,
          dimension: dimension.toUpperCase(),
          startIndex,
          endIndex,
        },
        destinationIndex,
      },
    }]);

    return {
      sheet: sheetInfo.title,
      dimension,
      from: `${startIndex}-${endIndex - 1}`,
      to: destinationIndex,
    };
  }

  // ===== SPREADSHEET PROPERTIES =====

  /**
   * Update spreadsheet properties (title, locale, etc.)
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {Object} properties - { title, locale, timeZone, autoRecalc }
   */
  async updateSpreadsheetProperties(spreadsheetId, properties) {
    const fields = [];
    const props = {};

    if (properties.title !== undefined) {
      props.title = properties.title;
      fields.push('title');
    }
    if (properties.locale !== undefined) {
      props.locale = properties.locale;
      fields.push('locale');
    }
    if (properties.timeZone !== undefined) {
      props.timeZone = properties.timeZone;
      fields.push('timeZone');
    }
    if (properties.autoRecalc !== undefined) {
      props.autoRecalc = properties.autoRecalc;
      fields.push('autoRecalc');
    }

    await this.batchUpdate(spreadsheetId, [{
      updateSpreadsheetProperties: {
        properties: props,
        fields: fields.join(','),
      },
    }]);

    return {
      spreadsheetId,
      updated: fields,
    };
  }

  // ===== AUTO FILL =====

  /**
   * Auto-fill a range based on existing data
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {string|number} sheet - Sheet name or index
   * @param {Object} sourceRange - Source range with pattern { startRowIndex, endRowIndex, startColumnIndex, endColumnIndex }
   * @param {Object} destinationRange - Range to fill { startRowIndex, endRowIndex, startColumnIndex, endColumnIndex }
   * @param {boolean} useAlternateSeries - Use alternate series for fill
   */
  async autoFill(spreadsheetId, sheet, sourceRange, destinationRange, useAlternateSeries = false) {
    const sheetInfo = await this.getSheetInfo(spreadsheetId, sheet);

    // Determine fill direction and length
    const rowDiff = destinationRange.endRowIndex - sourceRange.endRowIndex;
    const colDiff = destinationRange.endColumnIndex - sourceRange.endColumnIndex;
    const fillLength = Math.max(rowDiff, colDiff);
    const dimension = rowDiff > colDiff ? 'ROWS' : 'COLUMNS';

    await this.batchUpdate(spreadsheetId, [{
      autoFill: {
        sourceAndDestination: {
          source: {
            sheetId: sheetInfo.sheetId,
            ...sourceRange,
          },
          dimension,
          fillLength,
        },
        useAlternateSeries,
      },
    }]);

    return {
      sheet: sheetInfo.title,
      sourceRange,
      destinationRange,
      fillLength,
      dimension,
    };
  }

  // ===== TEXT TO COLUMNS =====

  /**
   * Split text in a column by delimiter
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {string|number} sheet - Sheet name or index
   * @param {Object} range - Source range with text to split
   * @param {string} delimiter - Delimiter character (or 'AUTO' for auto-detect)
   * @param {string} delimiterType - 'CUSTOM', 'COMMA', 'SEMICOLON', 'PERIOD', 'SPACE', 'AUTODETECT'
   */
  async textToColumns(spreadsheetId, sheet, range, delimiter = null, delimiterType = 'AUTODETECT') {
    const sheetInfo = await this.getSheetInfo(spreadsheetId, sheet);

    const request = {
      textToColumns: {
        source: {
          sheetId: sheetInfo.sheetId,
          ...range,
        },
        delimiterType,
      },
    };

    if (delimiter && delimiterType === 'CUSTOM') {
      request.textToColumns.delimiter = delimiter;
    }

    await this.batchUpdate(spreadsheetId, [request]);

    return {
      sheet: sheetInfo.title,
      range,
      delimiterType,
      delimiter: delimiter || 'auto',
    };
  }

  // ===== RANDOMIZE RANGE =====

  /**
   * Randomize (shuffle) rows in a range
   * @param {string} spreadsheetId - The spreadsheet ID
   * @param {string|number} sheet - Sheet name or index
   * @param {Object} range - { startRowIndex, endRowIndex, startColumnIndex, endColumnIndex }
   */
  async randomizeRange(spreadsheetId, sheet, range) {
    const sheetInfo = await this.getSheetInfo(spreadsheetId, sheet);

    await this.batchUpdate(spreadsheetId, [{
      randomizeRange: {
        range: {
          sheetId: sheetInfo.sheetId,
          ...range,
        },
      },
    }]);

    return {
      sheet: sheetInfo.title,
      range,
      message: 'Rows randomized',
    };
  }
}
