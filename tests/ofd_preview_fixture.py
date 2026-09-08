"""Synthetic OFD page tree; no invoice/customer documents are embedded."""
import io
import zipfile
from pathlib import Path
from PIL import Image, ImageDraw

NS = 'xmlns:ofd="http://www.ofdspec.org/2016"'


def write_ofd(path: Path) -> None:
    stamp = Image.new("RGBA", (100, 100), (255, 255, 255, 0))
    draw = ImageDraw.Draw(stamp)
    draw.ellipse((5, 5, 95, 95), outline=(200, 0, 0), width=5)
    draw.text((28, 44), "TEST", fill=(200, 0, 0))
    png = io.BytesIO()
    stamp.save(png, format="PNG")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("OFD.xml", f'<ofd:OFD {NS} Version="1.0" DocType="OFD"><ofd:DocBody>'
                          '<ofd:DocInfo><ofd:DocID>synthetic-preview</ofd:DocID></ofd:DocInfo>'
                          '<ofd:DocRoot>Doc_0/Document.xml</ofd:DocRoot></ofd:DocBody></ofd:OFD>')
        archive.writestr("Doc_0/Document.xml", f'<ofd:Document {NS}><ofd:CommonData>'
                          '<ofd:MaxUnitID>100</ofd:MaxUnitID><ofd:PageArea><ofd:PhysicalBox>0 0 180 100</ofd:PhysicalBox></ofd:PageArea>'
                          '<ofd:DocumentRes>Res.xml</ofd:DocumentRes></ofd:CommonData><ofd:Pages>'
                          '<ofd:Page ID="1" BaseLoc="Pages/Page_0/Content.xml"/>'
                          '<ofd:Page ID="2" BaseLoc="Pages/Page_1/Content.xml"/></ofd:Pages></ofd:Document>')
        archive.writestr("Doc_0/Res.xml", f'<ofd:Res {NS} BaseLoc="Res"><ofd:Fonts>'
                          '<ofd:Font ID="5" FontName="宋体" FamilyName="宋体"/></ofd:Fonts>'
                          '<ofd:MultiMedias><ofd:MultiMedia ID="6" Type="Image" Format="PNG">'
                          '<ofd:MediaFile>stamp.png</ofd:MediaFile></ofd:MultiMedia></ofd:MultiMedias></ofd:Res>')
        archive.writestr("Doc_0/Res/stamp.png", png.getvalue())
        archive.writestr("Doc_0/Res/unused.png", png.getvalue())
        for page, size in enumerate(("180 100", "100 180")):
            archive.writestr(f"Doc_0/Pages/Page_{page}/Content.xml", f'<ofd:Page {NS}>'
                              f'<ofd:Area><ofd:PhysicalBox>0 0 {size}</ofd:PhysicalBox></ofd:Area>'
                              '<ofd:Content><ofd:Layer ID="10">'
                              '<ofd:TextObject ID="11" Boundary="8 8 80 12" Font="5" Size="5">'
                              f'<ofd:TextCode X="0" Y="6" DeltaX="g 10 5">预览测试 PAGE {page + 1}</ofd:TextCode></ofd:TextObject>'
                              '<ofd:TextObject ID="12" Boundary="8 22 80 12" Font="5" Size="4">'
                              '<ofd:TextCode X="0" Y="5" DeltaX="g 20 2.2">100.00 + 13.00 = 113.00</ofd:TextCode></ofd:TextObject>'
                              '<ofd:PathObject ID="13" Boundary="8 38 75 20" LineWidth="0.4" Stroke="true" Fill="false">'
                              '<ofd:StrokeColor Value="0 60 160"/><ofd:AbbreviatedData>M 0 0 L 75 0 L 75 20 L 0 20 C</ofd:AbbreviatedData>'
                              '</ofd:PathObject><ofd:ImageObject ID="14" Boundary="60 62 25 25" ResourceID="6" CTM="25 0 0 25 0 0"/>'
                              '</ofd:Layer></ofd:Content></ofd:Page>')
