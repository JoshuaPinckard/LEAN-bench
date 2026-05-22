using System;
using QuantConnect.Algorithm;
using QuantConnect.Data;

namespace QuantConnect.Algorithm.CSharp
{
    public class BacktestAlgorithm : QCAlgorithm
    {
        private int _bars = 0;

        public override void Initialize()
        {
            SetStartDate(2020, 1, 6);
            SetEndDate(2020, 1, 10);
            SetCash(100000);
            AddEquity("SPY", Resolution.Daily);
        }

        public override void OnData(Slice slice)
        {
            _bars++;
            if (_bars >= 2)
            {
                throw new InvalidOperationException("intentional OnData() failure after 2 bars");
            }
        }
    }
}
