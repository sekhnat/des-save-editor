"""Informational browser benchmark; no flaky wall-clock assertions.

Run from des-editor: python3 tests/benchmark_editor.py
"""
from pathlib import Path
import json
import os
import sys
from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
fixture = Path(os.environ.get('DES_SAVE_DIR', root.parent / '_SaveData/PPSA01341')) / 'SAVEDATA0PlayerProfile0/USR-DATA'

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto((root / 'des_editor.html').as_uri())
    if fixture.exists():
        page.set_input_files('#file', str(fixture))
    else:
        import des_save
        save = des_save.SaveFile()
        save.records = [des_save.Field(des_save.name_key('PLAYER_SOULS'), des_save.T_I32, (176).to_bytes(4, 'little'))]
        save.records += [des_save.Field(1000 + index, des_save.T_CONTAINER, children=[
            des_save.Field(2000 + inner, des_save.T_U16, inner.to_bytes(2, 'little')) for inner in range(5)])
            for index in range(200)]
        page.set_input_files('#file', {'name': 'USR-DATA', 'mimeType': 'application/octet-stream',
                                       'buffer': save.build()})
    page.wait_for_function('!!current()')
    print(json.dumps(page.evaluate('''() => {
      const s=current().save, median=values=>values.sort((a,b)=>a-b)[Math.floor(values.length/2)];
      const render=[], cold=[];
      for(let i=0;i<30;i++) {
        let start=performance.now(); renderEditor(); render.push(performance.now()-start);
        s.touch(); start=performance.now(); s.build(); cold.push(performance.now()-start);
      }
      const jsonBytes=document.querySelector('#json').value.length;
      const rawInputs=document.querySelectorAll('#alltable input').length;
      const build=s.build.bind(s); let builds=0;
      s.build=()=>{builds++;return build();};
      isDirty(current()); builds=0;
      for(let i=0;i<100;i++) isDirty(current());
      return {sampleBytes:current().original.length, records:s.flat.length,
              medianRenderMs:median(render), medianColdBuildMs:median(cold),
              buildsFor100UnchangedDirtyChecks:builds,hiddenRawInputs:rawInputs,hiddenJsonChars:jsonBytes};
    }'''), indent=2))
    browser.close()
