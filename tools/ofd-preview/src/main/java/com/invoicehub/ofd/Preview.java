package com.invoicehub.ofd;

import java.awt.image.BufferedImage;
import java.io.ByteArrayOutputStream;
import java.io.DataOutputStream;
import java.io.PrintStream;
import java.nio.file.Files;
import java.nio.file.Path;
import javax.imageio.ImageIO;
import org.ofdrw.converter.ImageMaker;
import org.ofdrw.converter.FontLoader;
import org.ofdrw.converter.CGTransformMap;
import org.ofdrw.converter.font.TrueTypeFont;
import org.ofdrw.core.basicStructure.pageObj.layer.block.TextObject;
import org.ofdrw.core.text.CT_CGTransform;
import org.dom4j.Element;
import org.ofdrw.core.basicType.ST_Box;
import org.ofdrw.reader.OFDReader;

/** One bounded page per process; the Python parent owns extraction and cleanup. */
public final class Preview {
    private static final long MAX_PIXELS = 30_000_000L;
    private static final int MAX_PNG_BYTES = 32 * 1024 * 1024;

    private static final class MissingGlyph extends RuntimeException {}

    private static void checkGlyphs(OFDReader reader, Element element, int depth) throws Exception {
        if (depth > 128) throw new IllegalArgumentException();
        if (element.getName().equals("TextObject")) {
            TextObject object = new TextObject(element);
            var definition = reader.getResMgt().getFont(object.getFont().toString());
            if (definition == null) throw new MissingGlyph();
            TrueTypeFont font = FontLoader.getInstance().loadFontSimilar(reader.getResourceLocator(), definition).getFont();
            if (font == null) throw new MissingGlyph();
            CGTransformMap transforms = new CGTransformMap(object);
            int index = 0;
            for (Element text : element.elements("TextCode")) {
                String value = text.getText();
                for (int offset = 0; offset < value.length();) {
                    CT_CGTransform transform = transforms.get(index);
                    if (transform != null) {
                        int count = transform.getCodeCount();
                        if (count < 1 || offset + count > value.length()) throw new MissingGlyph();
                        offset += count; index += count;
                    } else {
                        char c = value.charAt(offset++); index++;
                        // OFDRW silently omits null cmap glyphs; detect this before
                        // publishing a PNG. Explicit CGTransform glyphs use their own map.
                        if (!Character.isWhitespace(c) && Character.getType(c) != Character.FORMAT
                            && (font.getUnicodeCmapLookup() == null || font.getUnicodeCmapLookup().getGlyphId(c) == 0
                                || font.getUnicodeGlyph(c) == null)) throw new MissingGlyph();
                    }
                }
            }
        }
        for (Element child : element.elements()) checkGlyphs(reader, child, depth + 1);
    }

    public static void main(String[] args) {
        DataOutputStream output = new DataOutputStream(System.out);
        // Third-party diagnostic output must never corrupt the binary PNG protocol.
        System.setOut(new PrintStream(System.err));
        try {
            if (args.length != 2) throw new IllegalArgumentException();
            int page = Integer.parseInt(args[1]);
            ImageIO.setUseCache(false);
            // OFD frequently names Windows Chinese fonts without embedding them.
            // On macOS use its installed Songti as the fallback, instead of the
            // upstream arbitrary first font which may contain no Chinese glyphs.
            if (System.getProperty("os.name").startsWith("Mac")) {
                Path songti = Path.of("/System/Library/Fonts/Supplemental/Songti.ttc");
                if (Files.isRegularFile(songti)) {
                    FontLoader fonts = FontLoader.getInstance();
                    for (String name : new String[]{"宋体", "SimSun", "仿宋", "FangSong"}) {
                        if (fonts.getSystemFontPath(null, name) == null) fonts.addSystemFontMapping(name, songti.toString());
                    }
                }
            }
            try (OFDReader reader = new OFDReader(args[0], false)) {
                int count = reader.getNumberOfPages();
                if (count < 1 || count > 200 || page < 1 || page > count) throw new IllegalArgumentException();
                double ppm = 150.0 / 25.4;
                ST_Box box = reader.getPageInfo(page).getSize();
                long width = Math.round(box.getWidth() * ppm);
                long height = Math.round(box.getHeight() * ppm);
                // Check before ImageMaker allocates: page dimensions are untrusted OFD data.
                if (!Double.isFinite(box.getWidth()) || !Double.isFinite(box.getHeight())
                    || width < 1 || height < 1 || width > MAX_PIXELS || height > MAX_PIXELS
                    || width * height > MAX_PIXELS) throw new IllegalArgumentException();
                for (var layer : reader.getPageInfo(page).getAllLayer()) checkGlyphs(reader, layer, 0);
                BufferedImage image = new ImageMaker(reader, ppm).makePage(page - 1);
                if (org.slf4j.impl.StaticLoggerBinder.incomplete()) throw new IllegalStateException();
                ByteArrayOutputStream png = new ByteArrayOutputStream();
                if (!ImageIO.write(image, "png", png) || png.size() > MAX_PNG_BYTES) throw new IllegalArgumentException();
                output.writeInt(0x49484f31); // IHO1, width, height, length, PNG bytes (big endian).
                output.writeInt(image.getWidth());
                output.writeInt(image.getHeight());
                output.writeInt(png.size());
                png.writeTo(output);
                output.flush();
            }
        } catch (MissingGlyph error) {
            System.err.println("ofd_font_unavailable");
            System.exit(3);
        } catch (Throwable error) {
            // Paths, embedded text and third-party exception messages are private.
            System.err.println("ofd_page_render_failed");
            System.exit(2);
        }
    }
}
