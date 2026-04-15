FontyMon v2.2 - A vector TTF/WOFF font converter into ShaderToy/GLSL with splines
–––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––

FontyMon's GitHub home: https://github.com/mewza/fontymon

To encode special characters like TM or (R)  just wrap them in parenthesis
inside of the --chars string and make sure special characters are present in
the font itself, open "font_showcase_reg.html" to check which fonts support 
them.

Example produced ShaderToy/GLSL by fontmymon.py script are available here:
https://www.shadertoy.com/view/scsSRM<br>
https://www.shadertoy.com/view/scsSRN<br>
https://www.shadertoy.com/view/fcsSRj<br>
https://www.shadertoy.com/view/fclXR2<br>
https://www.shadertoy.com/view/sfsXzj<br>
https://www.shadertoy.com/view/7fXSz2<br>

Example commands:

% python fontymon.py --chars "Hello world" --fire Zone99.woff
Demo: https://www.shadertoy.com/view/scsSRM
      https://www.shadertoy.com/view/7flXRM
      
% python fontymon.py --chars "Hello world" --extrude .3 --size 12 Zone99.woff
Demo: https://www.shadertoy.com/view/scsSRN

% python fontymon.py Zone99.woff  --chars "Hello world" --spell --spell-ch 0.15 --spell-draw 4.0 --spell-pause 2.0 --spell-color 0.8,0.4,0.1 --spell-hue-speed 0.05 --spell-glow 5.0
Demo: https://www.shadertoy.com/view/7fXSz2

% python fontymon.py Zone99.woff --chars "Matrix Loaded" --matrix
Demo: https://www.shadertoy.com/view/fcsSRj

% python fontymon.py DustHomeMedium.woff  --chars "Surrealizer(R)" --sweep
% python fontymon.py DustHomeMedium.woff  --chars "Surrealizer(R)" --sweep-3d
Demo: https://www.shadertoy.com/view/fclXR2

Contact the developer
–––––––––––––––––––––

Dmitry Boldyrev
Email: subband@gmail.com or
       subband@protonmail.com

Donations accepted via PayPal: subband@protonmail.com

I am not rich monetarily (honest, and as of today yet at least) and would appreciate a donation of any amount you can
afford if you feel like supporting me and this project, I spent my own money and time making this perfect
for you! Big THANK YOU from me if you decide to do so, but if not, enjoy using it anyway.







