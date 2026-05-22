using QuantConnect.Algorithm;
using QuantConnect.Data;

namespace QuantConnect.Algorithm.CSharp
{
    public class BacktestAlgorithm : QCAlgorithm
    {
        private Symbol _spy;
        private bool _bought = false;

        public override void Initialize()
        {
            SetStartDate(2020, 1, 6);
            SetEndDate(2020, 1, 10);
            SetCash(100000);
            _spy = AddEquity("SPY", Resolution.Daily).Symbol;
        }

        public override void OnData(Slice slice)
        {
            if (!_bought && slice.Bars.ContainsKey(_spy))
            {
                SetHoldings(_spy, 1.0);
                _bought = true;
            }
        }
    }
}
