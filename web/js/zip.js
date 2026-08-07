// ===========================================================
// Aeronis - minimal, dependency-free ZIP writer.
//
// Used to bundle several exported KMZ files into a single .zip
// download (see exportAllMissions in waypoints.js) instead of
// triggering one browser download per mission.
//
// Uses the "store" method (no compression, method 0): KMZ files are
// already a compressed archive internally, so re-compressing them
// would gain little, and skipping DEFLATE keeps this self-contained
// with no external library / CDN dependency.
// ===========================================================

const _CRC32_TABLE = (() => {
    const table = new Uint32Array(256);
    for (let n = 0; n < 256; n++) {
        let c = n;
        for (let k = 0; k < 8; k++) {
            c = (c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1);
        }
        table[n] = c >>> 0;
    }
    return table;
})();

function crc32(bytes) {
    let crc = 0xFFFFFFFF;
    for (let i = 0; i < bytes.length; i++) {
        crc = _CRC32_TABLE[(crc ^ bytes[i]) & 0xFF] ^ (crc >>> 8);
    }
    return (crc ^ 0xFFFFFFFF) >>> 0;
}

function _dosDateTime(date) {
    const dosTime = ((date.getHours() & 0x1F) << 11) | ((date.getMinutes() & 0x3F) << 5) | ((Math.floor(date.getSeconds() / 2)) & 0x1F);
    const dosDate = (((date.getFullYear() - 1980) & 0x7F) << 9) | (((date.getMonth() + 1) & 0xF) << 5) | (date.getDate() & 0x1F);
    return { dosTime, dosDate };
}

/**
 * Builds a valid, uncompressed .zip archive from a list of files.
 *
 * @param {Array<{name: string, data: Uint8Array}>} files
 * @returns {Uint8Array} the complete zip file's bytes
 */
function buildZip(files) {
    const { dosTime, dosDate } = _dosDateTime(new Date());
    const localChunks = [];
    const centralEntries = [];
    let offset = 0;

    for (const file of files) {
        const nameBytes = new TextEncoder().encode(file.name);
        const data = file.data;
        const crc = crc32(data);

        const localHeader = new Uint8Array(30 + nameBytes.length);
        const lv = new DataView(localHeader.buffer);
        lv.setUint32(0, 0x04034b50, true);   // local file header signature
        lv.setUint16(4, 20, true);           // version needed to extract
        lv.setUint16(6, 0, true);            // general purpose flags
        lv.setUint16(8, 0, true);            // compression method: store
        lv.setUint16(10, dosTime, true);
        lv.setUint16(12, dosDate, true);
        lv.setUint32(14, crc, true);
        lv.setUint32(18, data.length, true); // compressed size
        lv.setUint32(22, data.length, true); // uncompressed size
        lv.setUint16(26, nameBytes.length, true);
        lv.setUint16(28, 0, true);           // extra field length
        localHeader.set(nameBytes, 30);

        localChunks.push(localHeader, data);
        centralEntries.push({ nameBytes, crc, size: data.length, offset });
        offset += localHeader.length + data.length;
    }

    const centralChunks = [];
    let centralSize = 0;
    for (const entry of centralEntries) {
        const header = new Uint8Array(46 + entry.nameBytes.length);
        const dv = new DataView(header.buffer);
        dv.setUint32(0, 0x02014b50, true);   // central directory signature
        dv.setUint16(4, 20, true);           // version made by
        dv.setUint16(6, 20, true);           // version needed
        dv.setUint16(8, 0, true);            // flags
        dv.setUint16(10, 0, true);           // compression method: store
        dv.setUint16(12, dosTime, true);
        dv.setUint16(14, dosDate, true);
        dv.setUint32(16, entry.crc, true);
        dv.setUint32(20, entry.size, true);
        dv.setUint32(24, entry.size, true);
        dv.setUint16(28, entry.nameBytes.length, true);
        dv.setUint16(30, 0, true);           // extra length
        dv.setUint16(32, 0, true);           // comment length
        dv.setUint16(34, 0, true);           // disk number start
        dv.setUint16(36, 0, true);           // internal attrs
        dv.setUint32(38, 0, true);           // external attrs
        dv.setUint32(42, entry.offset, true);
        header.set(entry.nameBytes, 46);

        centralChunks.push(header);
        centralSize += header.length;
    }

    const eocd = new Uint8Array(22);
    const ev = new DataView(eocd.buffer);
    ev.setUint32(0, 0x06054b50, true);       // end of central directory signature
    ev.setUint16(4, 0, true);                // disk number
    ev.setUint16(6, 0, true);                // disk with central dir
    ev.setUint16(8, centralEntries.length, true);
    ev.setUint16(10, centralEntries.length, true);
    ev.setUint32(12, centralSize, true);
    ev.setUint32(16, offset, true);          // offset of central dir
    ev.setUint16(20, 0, true);               // comment length

    const allChunks = [...localChunks, ...centralChunks, eocd];
    const totalLength = allChunks.reduce((sum, c) => sum + c.length, 0);
    const result = new Uint8Array(totalLength);
    let pos = 0;
    for (const chunk of allChunks) {
        result.set(chunk, pos);
        pos += chunk.length;
    }
    return result;
}
